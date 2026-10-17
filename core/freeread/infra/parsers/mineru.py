"""MinerU 4.x（effort=medium，即本地版面 / 公式 / OCR / 表格模型，不使用 VLM）。

原生输出：raw/middle.json（docvortex.middle 2.0）。坐标为 0–1 归一化，页尺寸（pt）在
extensions.docvortex_layout.pages 中。块已按阅读顺序排列。
"""

import json

from freeread.domain.ir.models import BlockType
from freeread.infra.parsers.base import ParserCaps, RawLayout
from freeread.infra.parsers.normalize_common import RawBlock, build_document
from freeread.infra.parsers.subprocess_engine import SubprocessParser

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


class MinerUNormalizer:
    engine = "mineru"
    version = "0.1.0"

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

    from freeread.infra.parsers.normalize_common import merge_continuations

    blocks = merge_continuations(blocks, cont)
    return build_document(
        blocks, pdf_sha256=pdf_sha256, pages=pages, engine="mineru", engine_version=engine_version
    )
