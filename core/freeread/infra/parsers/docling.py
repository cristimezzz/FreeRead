"""Docling 2.x（版面 + TableFormer + 公式 LaTeX 增强 + 自动 OCR）。

原生输出：raw/docling.json（DoclingDocument.export_to_dict()）。阅读顺序为 body 树的前序遍历；
坐标多为左下原点（coord_origin=BOTTOMLEFT），需要翻转 y 轴；页码从 1 开始。
"""

import html as htmllib
import json

from freeread.domain.ir.models import BlockType
from freeread.infra.parsers.base import ParserCaps, RawLayout
from freeread.infra.parsers.normalize_common import RawBlock, build_document
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


def docling_parser() -> SubprocessParser:
    return SubprocessParser(
        "docling", ParserCaps(formulas=True, tables=True, ocr=True, needs_gpu=False)
    )


class DoclingNormalizer:
    engine = "docling"
    version = "0.1.0"

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

    def add(bt: BlockType, item: dict, **kw) -> None:
        a = anchors(item)
        if not a:
            return
        rb = RawBlock(type=bt, page=a[0][0], bbox=a[0][1], **kw)
        rb.extra_anchors = a[1:]
        blocks.append(rb)

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

    return build_document(
        blocks, pdf_sha256=pdf_sha256, pages=pages, engine="docling", engine_version=engine_version
    )
