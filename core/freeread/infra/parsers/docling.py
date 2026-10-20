"""Docling 2.x（版面 + TableFormer + 公式 LaTeX 增强 + 自动 OCR）。

原生输出：raw/docling.json（DoclingDocument.export_to_dict()）。阅读顺序为 body 树的前序遍历；
坐标多为左下原点（coord_origin=BOTTOMLEFT），需要翻转 y 轴；页码从 1 开始。
"""

import html as htmllib
import json
import re
from collections.abc import Callable

from freeread.domain.ir.models import BlockType
from freeread.infra.parsers.base import ParserCaps, RawLayout
from freeread.infra.parsers.normalize_common import (
    AFFIL_RE,
    CAPTION_LABEL_RE,
    CJK_RE,
    HEADING_NUMBER_RE,
    RawBlock,
    build_document,
    clean_text,
    mark_reference_section,
)
from freeread.infra.parsers.subprocess_engine import SubprocessParser

LABEL_MAP = {
    "title": BlockType.TITLE,
    "section_header": BlockType.HEADING,
    "text": BlockType.PARAGRAPH,
    "paragraph": BlockType.PARAGRAPH,
    "list_item": BlockType.LIST_ITEM,
    "caption": BlockType.CAPTION,
    "formula": BlockType.EQUATION,
    "footnote": BlockType.FOOTNOTE,
    "code": BlockType.CODE,
    "reference": BlockType.REFERENCE_ENTRY,
    "document_index": BlockType.OTHER,
    "checkbox_selected": BlockType.OTHER,
    "checkbox_unselected": BlockType.OTHER,
}
DROP_LABELS = {"page_header", "page_footer"}


def docling_parser(device: Callable[[], str] | None = None) -> SubprocessParser:
    return SubprocessParser(
        "docling",
        ParserCaps(formulas=True, tables=True, ocr=True, needs_gpu=False),
        device=device,
    )


class DoclingNormalizer:
    engine = "docling"
    version = "0.2.0"

    def normalize(self, raw: RawLayout, pdf_sha256: str):
        data = json.loads((raw.raw_dir / "docling.json").read_text(encoding="utf-8"))
        return normalize_docling(data, pdf_sha256, raw.engine_version)


def _resolve(data: dict, ref: str) -> dict:
    _, coll, idx = ref.split("/")
    return data[coll][int(idx)]


def table_html(item: dict) -> str | None:
    d = item.get("data") or {}
    cells = d.get("table_cells") or []
    if not cells:
        return None
    nrows = d.get("num_rows") or (max(c["end_row_offset_idx"] for c in cells))
    ncols = d.get("num_cols") or (max(c["end_col_offset_idx"] for c in cells))
    start = {(c["start_row_offset_idx"], c["start_col_offset_idx"]): c for c in cells}
    covered: set[tuple[int, int]] = set()
    rows = []
    for r in range(nrows):
        tds = []
        for col in range(ncols):
            if (r, col) in covered:
                continue
            c = start.get((r, col))
            if c is None:
                tds.append("<td></td>")
                continue
            rs = c["end_row_offset_idx"] - c["start_row_offset_idx"]
            cs = c["end_col_offset_idx"] - c["start_col_offset_idx"]
            for rr in range(r, r + rs):
                for cc in range(col, col + cs):
                    covered.add((rr, cc))
            tag = "th" if c.get("column_header") else "td"
            attrs = (f' rowspan="{rs}"' if rs > 1 else "") + (f' colspan="{cs}"' if cs > 1 else "")
            tds.append(f"<{tag}{attrs}>{htmllib.escape(c.get('text', ''))}</{tag}>")
        rows.append("<tr>" + "".join(tds) + "</tr>")
    return "<table>" + "".join(rows) + "</table>"


SECTION_NAME_RE = re.compile(
    r"^\s*(\d+[.\s]*)?(introduction|background|(materials?\s+and\s+)?methods?|results|discussion"
    r"|conclusions?|acknowledge?ments?|references|abstract|summary|highlights|graphical\s+abstract"
    r"|引言|前言|摘\s*要|材料与方法|方法|结果|讨论|结论|参考文献)\b",
    re.IGNORECASE,
)
# 任意页：收稿 / 接受日期（须含年份）、通讯作者、"全文及作者单位"
FOOTNOTE_ANY_RE = re.compile(
    r"^\s*((received|accepted|revised|published(\s+online)?|manuscript\s+received)\b[^.]{0,60}?\b(19|20)\d{2}"
    r"|收稿日期|接受日期|接收日期|修回日期|在线发布日期"
    r"|[*∗†‡§]?\s*(corresponding\s+authors?\b|to\s+whom\s+correspondence|correspondence\s+(to|should\s+be\s+addressed))"
    r"|[*∗]?\s*通[讯信]作者|full\s+article\s+and\s+list\s+of\s+author|全文及作者单位)",
    re.IGNORECASE,
)
# 仅首页：版权、DOI、作者贡献、利益声明等刊物小字
FOOTNOTE_FIRST_PAGE_RE = re.compile(
    r"^\s*(copyright\b|©|doi\s*:|https?://doi\.org|author\s+contributions\s*:|the\s+authors\s+declare"
    r"|competing\s+interests?\s*:|this\s+(open\s+access\s+)?article\s+(is|contains)|data\s+deposition"
    r"|present\s+address|supplemental\s+material\s+available)",
    re.IGNORECASE,
)
FOOTNOTE_MARKER_RE = re.compile(r"^\s*(\d{1,2}|[*∗†‡§¶#]|[a-z])\s?[A-Z一-鿿]")
REF_AUTHOR_RE = re.compile(
    r"^\s*(\[?\d{1,4}[\].)]?\s*)?[A-ZÀ-ÖØ-Þ][\w'’-]*(\s[A-Z][\w'’-]+)?,?\s+(([A-Z]\.\s?-?){1,3}|[A-Z]{1,3}\b)"
)
YEAR_RE = re.compile(r"\b(19|20)\d{2}[a-z]?\b")
PAGES_RE = re.compile(r"\d+\s?[–-]\s?\d+")
NUM_MARKER_RE = re.compile(r"^\[?\d{1,4}[\].)]?$")


def mark_title(blocks: list[RawBlock], pages: list[tuple[float, float]]) -> None:
    """Docling 常把论文题目标成 section_header：首页上部最高的、像题目的 heading → title。"""
    if not pages or any(b.type == BlockType.TITLE and b.page == 0 for b in blocks):
        return
    h = pages[0][1]
    cands = []
    for i, b in enumerate(blocks):
        if b.page != 0 or b.type != BlockType.HEADING or b.bbox[1] > h * 0.45:
            continue
        t = clean_text(b.plain_text())
        words = len(re.findall(r"[^\W\d_]+", t))
        if not (words >= 3 or len(CJK_RE.findall(t)) >= 6):
            continue
        if t.endswith((":", "：")) or HEADING_NUMBER_RE.match(t) or SECTION_NAME_RE.match(t):
            continue
        cands.append(i)
    if cands:
        best = max(cands, key=lambda i: (blocks[i].bbox[3] - blocks[i].bbox[1], -i))
        blocks[best].type, blocks[best].level = BlockType.TITLE, None


def mark_footnotes(blocks: list[RawBlock], pages: list[tuple[float, float]]) -> None:
    """Docling 把首页底部的单位、通讯作者、收稿日期、版权行等多标成 text：按关键词 / 位置改为 footnote。"""
    for b in blocks:
        if b.type not in (
            BlockType.PARAGRAPH,
            BlockType.LIST_ITEM,
            BlockType.CAPTION,
            BlockType.OTHER,
        ):
            continue
        t = clean_text(b.plain_text())
        if b.type == BlockType.CAPTION and CAPTION_LABEL_RE.match(t):
            continue
        hit = bool(FOOTNOTE_ANY_RE.match(t))
        if not hit and b.page == 0 and pages:
            h = pages[0][1]
            hit = bool(
                FOOTNOTE_FIRST_PAGE_RE.match(t)
                or (b.bbox[1] > h * 0.4 and FOOTNOTE_MARKER_RE.match(t) and AFFIL_RE.search(t[:80]))
                or (b.bbox[1] > h * 0.8 and AFFIL_RE.search(t[:60]))
            )
        if hit:
            b.type = BlockType.FOOTNOTE


def _ref_like(t: str) -> bool:
    if len(t) > 1500:
        return False
    if REF_AUTHOR_RE.match(t):
        return bool(YEAR_RE.search(t) or PAGES_RE.search(t))
    return bool(re.match(r"^\s*\[?\d", t) and YEAR_RE.search(t) and "et al" in t)


def mark_reference_runs(blocks: list[RawBlock], markers: dict[int, str]) -> None:
    """没有 "References" 标题时（如 Nature），连续 ≥ 3 条像文献条目的列表项 → reference_entry。
    Docling 把编号放在 marker 里，这里补回正文开头，以便 Reference.id 取到编号。"""

    def flush(run: list[int]) -> None:
        hits = [i for i in run if _ref_like(clean_text(blocks[i].plain_text()))]
        if len(hits) >= 3 and len(hits) * 2 >= len(run):
            for i in range(hits[0], hits[-1] + 1):
                if blocks[i].type == BlockType.LIST_ITEM:
                    blocks[i].type = BlockType.REFERENCE_ENTRY

    run: list[int] = []
    for i, b in enumerate(blocks):
        if b.type == BlockType.LIST_ITEM:
            run.append(i)
        elif b.type not in (
            BlockType.FIGURE,
            BlockType.TABLE,
            BlockType.CAPTION,
            BlockType.FOOTNOTE,
        ):
            flush(run)
            run = []
    flush(run)

    mark_reference_section(blocks)
    for b in blocks:
        m = markers.get(id(b), "").strip()
        if (
            b.type == BlockType.REFERENCE_ENTRY
            and NUM_MARKER_RE.match(m)
            and not b.text.startswith(m)
        ):
            b.text = f"{m} {b.text}"


def normalize_docling(data: dict, pdf_sha256: str, engine_version: str):
    page_nos = sorted(int(k) for k in data["pages"])
    sizes = {int(k): (v["size"]["width"], v["size"]["height"]) for k, v in data["pages"].items()}
    pages = [sizes[n] for n in range(1, max(page_nos) + 1)] if page_nos else []

    def anchors(item: dict) -> list[tuple[int, tuple]]:
        out = []
        for prov in item.get("prov") or []:
            pn = prov["page_no"]
            _, h = sizes.get(pn, (0, 0))
            bb = prov["bbox"]
            if bb.get("coord_origin", "BOTTOMLEFT") == "BOTTOMLEFT":
                box = (bb["l"], h - bb["t"], bb["r"], h - bb["b"])
            else:
                box = (bb["l"], bb["t"], bb["r"], bb["b"])
            out.append((pn - 1, box))
        return out

    blocks: list[RawBlock] = []
    emitted: set[str] = set()
    markers: dict[
        int, str
    ] = {}  # id(RawBlock) → 列表项编号（Docling 把 "1." 从正文里拆出放在 marker）

    def add(bt: BlockType, item: dict, **kw) -> None:
        a = anchors(item)
        if not a:
            return
        rb = RawBlock(type=bt, page=a[0][0], bbox=a[0][1], **kw)
        rb.extra_anchors = a[1:]
        blocks.append(rb)
        if item.get("marker"):
            markers[id(rb)] = item["marker"]

    def visit(ref: str) -> None:
        if ref in emitted:
            return
        emitted.add(ref)
        item = _resolve(data, ref)
        if item.get("content_layer") == "furniture":
            return
        kind = ref.split("/")[1]
        label = item.get("label")

        if kind == "groups":
            if label == "inline":
                # 行内组：文本 + 行内公式拼成一个段落
                segs, provs = [], []
                for ch in item.get("children", []):
                    sub = _resolve(data, ch["$ref"])
                    emitted.add(ch["$ref"])
                    if sub.get("label") == "formula":
                        segs.append(("math", sub.get("text") or sub.get("orig") or ""))
                    else:
                        segs.append(("text", " " + (sub.get("text") or "") + " "))
                    provs.extend(sub.get("prov") or [])
                if provs:
                    first = {"prov": provs}
                    a = anchors(first)
                    pg = a[0][0]
                    same = [b for p, b in a if p == pg]
                    box = (
                        min(b[0] for b in same),
                        min(b[1] for b in same),
                        max(b[2] for b in same),
                        max(b[3] for b in same),
                    )
                    blocks.append(
                        RawBlock(type=BlockType.PARAGRAPH, page=pg, bbox=box, segments=segs)
                    )
                return
            for ch in item.get("children", []):
                visit(ch["$ref"])
            return

        if kind == "pictures":
            add(BlockType.FIGURE, item)
            for c in item.get("captions", []):
                visit(c["$ref"])
            for c in item.get("footnotes", []):
                visit(c["$ref"])
            # 图内文字（坐标轴标签等）不进入 IR
            for ch in item.get("children", []):
                emitted.add(ch["$ref"])
            return

        if kind == "tables":
            add(BlockType.TABLE, item, html=table_html(item))
            for c in item.get("captions", []):
                visit(c["$ref"])
            for c in item.get("footnotes", []):
                f = _resolve(data, c["$ref"])
                emitted.add(c["$ref"])
                add(BlockType.FOOTNOTE, f, text=f.get("text", ""))
            for ch in item.get("children", []):
                emitted.add(ch["$ref"])
            return

        if label in DROP_LABELS:
            return
        bt = LABEL_MAP.get(label, BlockType.PARAGRAPH if kind == "texts" else BlockType.OTHER)
        if bt == BlockType.EQUATION:
            latex = item.get("text") or None
            add(bt, item, latex=latex, flags=[] if latex else ["no_latex"])
        elif bt == BlockType.HEADING:
            add(bt, item, text=item.get("text", ""), level=item.get("level"))
        else:
            add(bt, item, text=item.get("text", ""))
        for ch in item.get("children", []):
            visit(ch["$ref"])

    for ch in data["body"].get("children", []):
        visit(ch["$ref"])

    mark_title(blocks, pages)
    mark_footnotes(blocks, pages)
    mark_reference_runs(blocks, markers)
    return build_document(
        blocks, pdf_sha256=pdf_sha256, pages=pages, engine="docling", engine_version=engine_version
    )
