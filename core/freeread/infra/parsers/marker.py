"""Marker 1.x（surya 版面 / OCR / texify 公式，不启用 LLM）。

原生输出：raw/marker.json（JSONRenderer 的块树）。页面 → 块（含 *Group 容器）→ 行 / span；
叶子块的 html 中，行内公式为 <math>…</math>，显示公式为 <math display="block">…</math>。
polygon / bbox 以页面 bbox 为参照系（PDF 点、左上原点）。块顺序即阅读顺序。
"""

import json
import re
from html.parser import HTMLParser

from freeread.domain.ir.models import BlockType
from freeread.infra.parsers.base import ParserCaps, RawLayout
from freeread.infra.parsers.normalize_common import RawBlock, build_document
from freeread.infra.parsers.subprocess_engine import SubprocessParser

TYPE_MAP = {
    "Text": BlockType.PARAGRAPH,
    "TextInlineMath": BlockType.PARAGRAPH,
    "SectionHeader": BlockType.HEADING,
    "Caption": BlockType.CAPTION,
    "Footnote": BlockType.FOOTNOTE,
    "Equation": BlockType.EQUATION,
    "Figure": BlockType.FIGURE,
    "Picture": BlockType.FIGURE,
    "Table": BlockType.TABLE,
    "Form": BlockType.TABLE,
    "TableOfContents": BlockType.OTHER,
    "ListItem": BlockType.LIST_ITEM,
    "Code": BlockType.CODE,
    "ComplexRegion": BlockType.PARAGRAPH,
    "Handwriting": BlockType.OTHER,
    "Reference": BlockType.REFERENCE_ENTRY,
}
DROP = {"PageHeader", "PageFooter", "Line", "Span", "Char"}
GROUPS = {"ListGroup", "PictureGroup", "FigureGroup", "TableGroup", "Page", "Document"}


def marker_parser() -> SubprocessParser:
    return SubprocessParser(
        "marker", ParserCaps(formulas=True, tables=True, ocr=True, needs_gpu=False)
    )


class _Segmenter(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.segs: list[tuple[str, str]] = []
        self._math: list[str] | None = None
        self.block_math = False
        self.heading_level: int | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "math":
            self._math = []
            if dict(attrs).get("display") == "block":
                self.block_math = True
        elif re.fullmatch(r"h[1-6]", tag) and self.heading_level is None:
            self.heading_level = int(tag[1])
        elif tag in ("br", "p", "li", "div"):
            self.segs.append(("text", " "))

    def handle_endtag(self, tag):
        if tag == "math" and self._math is not None:
            self.segs.append(("math", "".join(self._math)))
            self._math = None

    def handle_data(self, data):
        if self._math is not None:
            self._math.append(data)
        else:
            self.segs.append(("text", data))


def parse_html(html: str) -> _Segmenter:
    p = _Segmenter()
    p.feed(re.sub(r"<content-ref[^>]*>(</content-ref>)?", "", html or ""))
    p.close()
    return p


class MarkerNormalizer:
    engine = "marker"
    version = "0.1.0"

    def normalize(self, raw: RawLayout, pdf_sha256: str):
        data = json.loads((raw.raw_dir / "marker.json").read_text(encoding="utf-8"))
        info = json.loads((raw.raw_dir / "engine.json").read_text(encoding="utf-8"))
        return normalize_marker(data, pdf_sha256, raw.engine_version, info.get("page_sizes"))


PAGE_ID_RE = re.compile(r"^/page/(\d+)/")


def normalize_marker(
    data: dict, pdf_sha256: str, engine_version: str, page_sizes: list[list[float]] | None = None
):
    """page_sizes：PDF 全部页的尺寸（pt）。Marker 可能只处理了部分页（page_range），
    此时以页块 id（/page/<原页码>/…）定位原页，并把 Marker 坐标缩放到 PDF 尺寸。"""
    page_nodes = data["children"]
    idx = [
        int(m.group(1)) if (m := PAGE_ID_RE.match(pg["id"])) else i
        for i, pg in enumerate(page_nodes)
    ]
    if page_sizes:
        pages = [(w, h) for w, h in page_sizes]
    else:
        pages = [
            (pg["bbox"][2] - pg["bbox"][0], pg["bbox"][3] - pg["bbox"][1]) for pg in page_nodes
        ]
        idx = list(range(len(page_nodes)))

    blocks: list[RawBlock] = []

    scale: dict[int, tuple[float, float]] = {}
    for pg, pi in zip(page_nodes, idx, strict=True):
        mw, mh = pg["bbox"][2] - pg["bbox"][0], pg["bbox"][3] - pg["bbox"][1]
        scale[pi] = (pages[pi][0] / mw if mw else 1.0, pages[pi][1] / mh if mh else 1.0)

    def visit(node: dict, page_no: int) -> None:
        bt_name = node["block_type"]
        if bt_name in DROP:
            return
        if bt_name in GROUPS:
            for ch in node.get("children") or []:
                visit(ch, page_no)
            return
        bt = TYPE_MAP.get(bt_name, BlockType.OTHER)
        sx, sy = scale[page_no]
        x0, y0, x1, y1 = node["bbox"]
        bbox = (x0 * sx, y0 * sy, x1 * sx, y1 * sy)
        html = node.get("html") or ""
        img = next(iter((node.get("images") or {}).values()), None)
        if bt == BlockType.TABLE:
            m = re.search(r"<table.*</table>", html, re.DOTALL)
            blocks.append(
                RawBlock(type=bt, page=page_no, bbox=bbox, html=m.group(0) if m else None)
            )
            return
        if bt == BlockType.FIGURE:
            blocks.append(RawBlock(type=bt, page=page_no, bbox=bbox, image_path=img))
            return
        seg = parse_html(html)
        if bt == BlockType.EQUATION:
            latex = "".join(s for k, s in seg.segs if k == "math") or None
            blocks.append(
                RawBlock(
                    type=bt,
                    page=page_no,
                    bbox=bbox,
                    latex=latex,
                    flags=[] if latex else ["no_latex"],
                )
            )
            return
        has_math = any(k == "math" for k, _ in seg.segs)
        text = "".join(s for k, s in seg.segs if k == "text")
        blocks.append(
            RawBlock(
                type=bt,
                page=page_no,
                bbox=bbox,
                segments=seg.segs if has_math else [],
                text=text,
                level=seg.heading_level if bt == BlockType.HEADING else None,
            )
        )

    for pg, pi in zip(page_nodes, idx, strict=True):
        for ch in pg.get("children") or []:
            visit(ch, pi)

    partial = sorted(set(idx)) if page_sizes and len(set(idx)) < len(pages) else None
    return build_document(
        blocks,
        pdf_sha256=pdf_sha256,
        pages=pages,
        engine="marker",
        engine_version=engine_version,
        pages_parsed=partial,
    )
