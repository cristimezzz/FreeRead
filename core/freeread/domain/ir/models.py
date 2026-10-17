"""Document IR 模型。规范见 docs/02-document-ir.md。

导出 JSON Schema：
    python -c "import json; from freeread.domain.ir.models import Document; print(json.dumps(Document.model_json_schema(), ensure_ascii=False, indent=2))"
"""

import re
from enum import StrEnum

from pydantic import BaseModel, Field

IR_SCHEMA_VERSION = "0.1.0"

PLACEHOLDER_RE = re.compile(r"⟦([A-Za-z0-9_]+)⟧")


class BlockType(StrEnum):
    TITLE = "title"
    AUTHOR_INFO = "author_info"
    ABSTRACT = "abstract"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    EQUATION = "equation"
    FIGURE = "figure"
    TABLE = "table"
    CAPTION = "caption"
    CODE = "code"
    FOOTNOTE = "footnote"
    REFERENCE_ENTRY = "reference_entry"
    OTHER = "other"


TRANSLATABLE_TYPES = frozenset(
    {
        BlockType.TITLE,
        BlockType.ABSTRACT,
        BlockType.HEADING,
        BlockType.PARAGRAPH,
        BlockType.LIST_ITEM,
        BlockType.CAPTION,
        BlockType.FOOTNOTE,
    }
)


class InlineKind(StrEnum):
    MATH = "math"
    CITE = "cite"
    XREF = "xref"
    URL = "url"
    CODE = "code"


class Anchor(BaseModel):
    page: int = Field(ge=0, description="页码，从 0 开始")
    bbox: tuple[float, float, float, float] = Field(description="[x0, y0, x1, y1]，PDF 点，左上原点")


class Inline(BaseModel):
    key: str | None = None
    kind: InlineKind
    latex: str | None = None
    ref_ids: list[str] = []
    target_block_id: str | None = None
    url: str | None = None
    span: tuple[int, int] | None = None


class Block(BaseModel):
    id: str = Field(pattern=r"^b_\d{4,}$")
    type: BlockType
    order: int = Field(ge=0)
    section_id: str | None = None
    level: int | None = None
    text: str = ""
    inlines: list[Inline] = []
    latex: str | None = None
    html: str | None = None
    asset_id: str | None = None
    caption_of: str | None = None
    label: str | None = None
    anchors: list[Anchor] = []
    content_hash: str
    confidence: float | None = None
    flags: list[str] = []

    def placeholder_keys(self) -> list[str]:
        return PLACEHOLDER_RE.findall(self.text)


class Section(BaseModel):
    id: str
    title: str
    level: int
    parent_id: str | None = None
    heading_block_id: str | None = None
    block_range: tuple[str, str] | None = None


class Reference(BaseModel):
    id: str
    raw_block_id: str | None = None
    title: str | None = None
    authors: list[str] = []
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    linked_doc_id: str | None = None


class Asset(BaseModel):
    id: str
    kind: str = "image"
    path: str
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    width_px: int | None = None
    height_px: int | None = None


class PageInfo(BaseModel):
    index: int
    width: float
    height: float


class Source(BaseModel):
    pdf_sha256: str
    page_count: int
    pages: list[PageInfo]


class Author(BaseModel):
    name: str
    affiliation: str | None = None


class Meta(BaseModel):
    title: str | None = None
    authors: list[Author] = []
    year: int | None = None
    doi: str | None = None
    venue: str | None = None
    language: str | None = None
    zotero_key: str | None = None


class ParserInfo(BaseModel):
    engine: str
    engine_version: str
    normalizer_version: str
    created_at: str


class Document(BaseModel):
    schema_version: str = IR_SCHEMA_VERSION
    doc_id: str = Field(pattern=r"^d_[0-9a-f]{16}$")
    source: Source
    meta: Meta = Meta()
    parser: ParserInfo
    sections: list[Section] = []
    blocks: list[Block] = []
    references: list[Reference] = []
    assets: list[Asset] = []


def doc_id_from_sha256(pdf_sha256: str) -> str:
    return "d_" + pdf_sha256[:16].lower()


def validate_document(doc: Document) -> list[str]:
    """执行 JSON Schema 之外的规则检查（docs/02-document-ir.md §7），返回问题列表。"""
    problems: list[str] = []
    block_ids = {b.id for b in doc.blocks}
    section_ids = {s.id for s in doc.sections}
    asset_ids = {a.id for a in doc.assets}
    ref_ids = {r.id for r in doc.references}
    pages = {p.index: p for p in doc.source.pages}

    if len(block_ids) != len(doc.blocks):
        problems.append("duplicate block id")

    for i, b in enumerate(doc.blocks):
        if b.order != i:
            problems.append(f"{b.id}: order {b.order} != position {i}")
        if b.section_id is not None and b.section_id not in section_ids:
            problems.append(f"{b.id}: unknown section {b.section_id}")
        if b.caption_of is not None and b.caption_of not in block_ids:
            problems.append(f"{b.id}: caption_of unknown block {b.caption_of}")
        if b.asset_id is not None and b.asset_id not in asset_ids:
            problems.append(f"{b.id}: unknown asset {b.asset_id}")

        text_keys = set(b.placeholder_keys())
        inline_keys = {il.key for il in b.inlines if il.key is not None}
        if text_keys != inline_keys:
            problems.append(f"{b.id}: placeholder mismatch {sorted(text_keys ^ inline_keys)}")
        for il in b.inlines:
            missing = [r for r in il.ref_ids if r not in ref_ids]
            if missing:
                problems.append(f"{b.id}: unknown refs {missing}")
            if il.target_block_id is not None and il.target_block_id not in block_ids:
                problems.append(f"{b.id}: xref to unknown block {il.target_block_id}")

        for a in b.anchors:
            page = pages.get(a.page)
            if page is None:
                problems.append(f"{b.id}: anchor page {a.page} out of range")
                continue
            x0, y0, x1, y1 = a.bbox
            tol = 1.0
            if not (-tol <= x0 <= x1 <= page.width + tol and -tol <= y0 <= y1 <= page.height + tol):
                problems.append(f"{b.id}: bbox outside page {a.page}")

        if b.type == BlockType.EQUATION and not b.latex:
            problems.append(f"{b.id}: equation without latex")
        if b.type == BlockType.TABLE and not (b.html or b.asset_id):
            problems.append(f"{b.id}: table without html or asset")
        if b.type == BlockType.FIGURE and not b.asset_id:
            problems.append(f"{b.id}: figure without asset")

    return problems
