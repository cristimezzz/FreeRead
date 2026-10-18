"""MinerU 4.x（effort=medium，即本地版面 / 公式 / OCR / 表格模型，不使用 VLM）。

原生输出：raw/middle.json（docvortex.middle 2.0）。坐标为 0–1 归一化，页尺寸（pt）在
extensions.docvortex_layout.pages 中。块已按阅读顺序排列。
"""

import json
import re

from freeread.domain.ir.models import BlockType
from freeread.infra.parsers.base import ParserCaps, RawLayout
from freeread.infra.parsers.normalize_common import (
    BBox,
    RawBlock,
    build_document,
    merge_continuations,
)
from freeread.infra.parsers.subprocess_engine import SubprocessParser

# 子图标号："a" "(b)" "C." "(iv)"
SUBFIG_LABEL_RE = re.compile(r"^\s*[(\[]?([A-Za-z]|[ivx]{1,4})[)\]]?[.:]?\s*$")
FIGURE_LABEL_RE = re.compile(
    r"^\s*((supplementary\s+|extended\s+data\s+)?fig(ure)?s?\.?|scheme|图)\s*S?\d", re.IGNORECASE
)
SUBFIG_GAP = 20.0  # 同一张图的子图之间的最大间距（pt）

TYPE_MAP = {
    "doc_title": BlockType.TITLE,
    "title": BlockType.HEADING,
    "paragraph_title": BlockType.HEADING,
    "abstract": BlockType.ABSTRACT,
    "text": BlockType.PARAGRAPH,
    "ref_text": BlockType.REFERENCE_ENTRY,
    "list": BlockType.LIST_ITEM,
    "list_item": BlockType.LIST_ITEM,
    "equation": BlockType.EQUATION,
    "interline_equation": BlockType.EQUATION,
    "page_footnote": BlockType.FOOTNOTE,
    "aside_text": BlockType.OTHER,
    "index": BlockType.OTHER,
    "phonetic": BlockType.OTHER,
}
DROP = {"header", "footer", "page_number"}
CONTAINERS = {"image", "chart", "table", "code", "algorithm"}
PART_MAP = {
    "image_body": BlockType.FIGURE,
    "chart_body": BlockType.FIGURE,
    "table_body": BlockType.TABLE,
    "code_body": BlockType.CODE,
    "algorithm_body": BlockType.CODE,
}


def mineru_parser() -> SubprocessParser:
    return SubprocessParser(
        "mineru", ParserCaps(formulas=True, tables=True, ocr=True, needs_gpu=False)
    )


def _segments(content) -> list[tuple[str, str]]:
    if isinstance(content, str):
        return [("text", content)]
    segs: list[tuple[str, str]] = []
    for it in content or []:
        t = it.get("type")
        c = it.get("content")
        if t == "equation_inline":
            segs.append(("math", c or ""))
        elif isinstance(c, list):
            segs.extend(_segments(c))
        elif isinstance(c, str):
            segs.append(("text", c))
    return segs


def _has_math(segs: list[tuple[str, str]]) -> bool:
    return any(k == "math" for k, _ in segs)


def _gap(a: BBox, b: BBox) -> float:
    dx = max(0.0, b[0] - a[2], a[0] - b[2])
    dy = max(0.0, b[1] - a[3], a[1] - b[3])
    return max(dx, dy)


def _union(boxes: list[BBox]) -> BBox:
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def _find(parent: dict[int, int], i: int) -> int:
    while parent[i] != i:
        parent[i] = parent[parent[i]]
        i = parent[i]
    return i


def _is_subfig_label(b: RawBlock, figs: list[BBox]) -> bool:
    if b.type not in (BlockType.CAPTION, BlockType.PARAGRAPH, BlockType.OTHER, BlockType.HEADING):
        return False
    if not SUBFIG_LABEL_RE.match(b.plain_text()):
        return False
    # 图注类的单字母块一定是子图标号；正文类的只在紧挨着图时才算
    return b.type == BlockType.CAPTION or any(_gap(b.bbox, f) <= SUBFIG_GAP for f in figs)


def merge_subfigures(blocks: list[RawBlock]) -> list[RawBlock]:
    """MinerU 常把一张多面板图拆成多个 image 块，并把 "a" "(b)" 等子图标号识别为 caption。

    - 子图标号块一律丢弃（IR 约定：图内文字不单独成块）。
    - 同页上相互间距 ≤ SUBFIG_GAP 的 figure（经子图标号连通也算）构成一组；若组正下方紧接一个
      "Figure N / 图 N" 图注，且组内没有正文块，则合并为一个 figure，bbox 取并集，放在该图注之前。
    """
    drop: set[int] = set()
    insert_before: dict[int, RawBlock] = {}
    for page in sorted({b.page for b in blocks}):
        idx = [i for i, b in enumerate(blocks) if b.page == page]
        fig_idx = [i for i in idx if blocks[i].type == BlockType.FIGURE]
        if not fig_idx:
            label_idx = [i for i in idx if blocks[i].type == BlockType.CAPTION]
            drop.update(i for i in label_idx if _is_subfig_label(blocks[i], []))
            continue
        figs = [blocks[i].bbox for i in fig_idx]
        labels = [i for i in idx if _is_subfig_label(blocks[i], figs)]
        drop.update(labels)

        # 并查集：figure 与子图标号按间距连通
        nodes = fig_idx + labels
        parent = {i: i for i in nodes}
        for x in range(len(nodes)):
            for y in range(x + 1, len(nodes)):
                if _gap(blocks[nodes[x]].bbox, blocks[nodes[y]].bbox) <= SUBFIG_GAP:
                    parent[_find(parent, nodes[x])] = _find(parent, nodes[y])
        groups: dict[int, list[int]] = {}
        for i in nodes:
            groups.setdefault(_find(parent, i), []).append(i)

        captions = [
            i
            for i in idx
            if blocks[i].type == BlockType.CAPTION
            and i not in drop
            and FIGURE_LABEL_RE.match(blocks[i].plain_text())
        ]
        for members in groups.values():
            members_figs = sorted(i for i in members if blocks[i].type == BlockType.FIGURE)
            if len(members_figs) < 2:
                continue
            u = _union([blocks[i].bbox for i in members])
            below = [
                c
                for c in captions
                if u[3] - 10 <= blocks[c].bbox[1] <= u[3] + 40
                and min(u[2], blocks[c].bbox[2]) - max(u[0], blocks[c].bbox[0])
                >= 0.5 * min(u[2] - u[0], blocks[c].bbox[2] - blocks[c].bbox[0])
            ]
            if not below:
                continue
            # 并集内不能压到正文（否则说明这些 figure 并不属于同一张图）
            member_set = set(members)
            intrudes = False
            for i in idx:
                b = blocks[i]
                if i in member_set or i in drop or b.type == BlockType.FIGURE:
                    continue
                if len(b.plain_text()) < 30 and b.type not in (BlockType.TABLE, BlockType.EQUATION):
                    continue
                cx, cy = (b.bbox[0] + b.bbox[2]) / 2, (b.bbox[1] + b.bbox[3]) / 2
                if u[0] < cx < u[2] and u[1] < cy < u[3]:
                    intrudes = True
                    break
            if intrudes:
                continue
            merged = blocks[members_figs[0]]
            merged.bbox = u
            merged.image_path = None  # 引擎导出的是单个子图，整图由解析任务按 bbox 重新截取
            drop.update(members_figs)
            cap = min(below, key=lambda c: blocks[c].bbox[1])
            if cap in insert_before:
                # 两组子图（间距超过 SUBFIG_GAP）共用一个图注：并成同一张图，不能丢掉先到的那组
                prev = insert_before[cap]
                prev.bbox = _union([prev.bbox, merged.bbox])
            else:
                insert_before[cap] = merged  # 阅读顺序上整图紧挨在图注之前
    out: list[RawBlock] = []
    for i, b in enumerate(blocks):
        if i in insert_before:
            out.append(insert_before[i])
        if i not in drop:
            out.append(b)
    return out


class MinerUNormalizer:
    engine = "mineru"
    version = "0.2.0"

    def normalize(self, raw: RawLayout, pdf_sha256: str):
        middle = json.loads((raw.raw_dir / "middle.json").read_text(encoding="utf-8"))
        return normalize_middle(middle, pdf_sha256, raw.engine_version)


def normalize_middle(middle: dict, pdf_sha256: str, engine_version: str):
    layout = {p["page_idx"]: p for p in middle["extensions"]["docvortex_layout"]["pages"]}
    pages = [
        (layout[p["page_idx"]]["width_pt"], layout[p["page_idx"]]["height_pt"])
        for p in middle["pages"]
    ]
    parse_mode = middle.get("extensions", {}).get("mineru", {}).get("parse_mode")
    base_flags = ["ocr"] if parse_mode == "ocr" else []

    blocks: list[RawBlock] = []
    cont: list[bool] = []

    def emit(rb: RawBlock, c: bool = False) -> None:
        rb.flags = list(base_flags) + rb.flags
        blocks.append(rb)
        cont.append(c)

    for page_no, p in enumerate(middle["pages"]):
        w, h = pages[page_no]

        def to_pt(bb, w=w, h=h):
            x0, y0, x1, y1 = bb
            return (x0 * w, y0 * h, x1 * w, y1 * h)

        for b in p["blocks"]:
            t = b.get("type")
            if t in DROP:
                continue
            if t in CONTAINERS:
                for part in b.get("content") or []:
                    pt = part.get("type", "")
                    bb = to_pt(part.get("bbox") or b["bbox"])
                    if pt in PART_MAP:
                        bt = PART_MAP[pt]
                        html = part.get("content") if bt == BlockType.TABLE else None
                        if html:
                            # IR 约定：表格 HTML 内的行内公式统一为 <math>LaTeX</math>
                            html = html.replace("<eq>", "<math>").replace("</eq>", "</math>")
                        text = part.get("content") if bt == BlockType.CODE else ""
                        if bt == BlockType.CODE and isinstance(text, list):
                            text = "".join(s for _, s in _segments(text))
                        emit(
                            RawBlock(
                                type=bt,
                                page=page_no,
                                bbox=bb,
                                html=html or None,
                                text=text or "",
                                image_path=part.get("image_path"),
                            )
                        )
                    elif pt.endswith("_caption"):
                        segs = _segments(part.get("content"))
                        emit(RawBlock(type=BlockType.CAPTION, page=page_no, bbox=bb, segments=segs))
                    elif pt.endswith("_footnote"):
                        segs = _segments(part.get("content"))
                        emit(
                            RawBlock(type=BlockType.FOOTNOTE, page=page_no, bbox=bb, segments=segs)
                        )
                continue

            bt = TYPE_MAP.get(t, BlockType.OTHER)
            bb = to_pt(b["bbox"])
            if bt == BlockType.EQUATION:
                c = b.get("content")
                latex = c if isinstance(c, str) else "".join(s for _, s in _segments(c))
                emit(RawBlock(type=bt, page=page_no, bbox=bb, latex=latex or None))
                continue
            if (
                t == "list"
                and isinstance(b.get("content"), list)
                and any(isinstance(it.get("content"), list) for it in b["content"])
            ):
                for it in b["content"]:
                    segs = _segments(it.get("content"))
                    emit(
                        RawBlock(
                            type=BlockType.LIST_ITEM,
                            page=page_no,
                            bbox=to_pt(it.get("bbox") or b["bbox"]),
                            segments=segs if _has_math(segs) else [],
                            text="".join(s for _, s in segs),
                        )
                    )
                continue
            segs = _segments(b.get("content"))
            emit(
                RawBlock(
                    type=bt,
                    page=page_no,
                    bbox=bb,
                    segments=segs if _has_math(segs) else [],
                    text="".join(s for _, s in segs),
                    level=b.get("level") if bt == BlockType.HEADING else None,
                ),
                c=bool(b.get("continues_prev")),
            )

    blocks = merge_subfigures(merge_continuations(blocks, cont))
    return build_document(
        blocks, pdf_sha256=pdf_sha256, pages=pages, engine="mineru", engine_version=engine_version
    )
