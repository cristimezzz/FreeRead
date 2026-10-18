"""各引擎 Normalizer 的公共部分：把"按阅读顺序排列的 RawBlock 列表"组装成 Document IR。

引擎专属代码只需负责：类型映射、坐标换算（统一为 PDF 点、左上原点）、阅读顺序、行内公式切分。
其余（ID 编号、content_hash、占位符、章节树、图注配对、参考文献、校验）都在这里完成。
规范见 docs/02-document-ir.md。
"""

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime

from freeread.domain.ir.models import (
    Anchor,
    Asset,
    Block,
    BlockType,
    Document,
    Inline,
    InlineKind,
    Meta,
    PageInfo,
    ParserInfo,
    Reference,
    Section,
    Source,
    doc_id_from_sha256,
    validate_document,
)

NORMALIZER_VERSION = "0.2.0"

BBox = tuple[float, float, float, float]

CAPTION_LABEL_RE = re.compile(
    r"^\s*((?:Supplementary\s+|Extended\s+Data\s+)?(?:Fig(?:ure)?s?\.?|Table|Scheme|Algorithm)\s*S?\d+[a-z]?"
    r"|(?:图|表)\s*S?\d+)",
    re.IGNORECASE,
)
REFERENCES_HEADING_RE = re.compile(
    r"^\s*(\d+[.\s]*)?(references?(\s+and\s+notes)?|bibliography|literature\s+cited|参考文献)\s*:?\s*$",
    re.IGNORECASE,
)
HEADING_NUMBER_RE = re.compile(r"^\s*((?:\d+\.)*\d+)\.?\s+\S")
REF_NUMBER_RE = re.compile(r"^\s*\[?(\d{1,4})[\].)]?\s+\S")
CJK_RE = re.compile(r"[一-鿿]")

# ---- 首页前置内容（abstract / author_info）的关键词规则
ABSTRACT_HEAD_RE = re.compile(r"^\s*(abstract|summary|摘\s*要)\s*[:.：]?\s*$", re.IGNORECASE)
# "Abstract. The…" / "ABSTRACT The…" / "Abstract | …" / "摘要：…"
ABSTRACT_START_RE = re.compile(r"^\s*(abstract|摘\s*要)(\s*[:.：|—–-]\s*|\s+)(?=\S)", re.IGNORECASE)
KEYWORDS_RE = re.compile(
    r"^\s*(key\s*words?|index\s+terms|关键词)\b|^[^|]{2,40}(\|[^|]{2,40}){2,}$", re.IGNORECASE
)
# 作者区内出现但不属于作者信息、也不终止作者区的块（日期、DOI、开放获取标记等）
FRONT_SKIP_RE = re.compile(
    r"^\s*((received|accepted|revised|published|available\s+online|open\s+access|check\s+for\s+updates"
    r"|full\s+article|(research\s+)?article|copyright)\b|©|doi\s*:|https?://|www\."
    r"|收稿日期|接受日期|接收日期|修回日期|在线发布日期|全文及作者单位)",
    re.IGNORECASE,
)
# 出现即说明作者区已结束
FRONT_STOP_RE = re.compile(
    r"^\s*(key\s*words?|index\s+terms|edited\s+by|reviewed\s+by|(academic\s+)?editor\s*:|citation"
    r"|specialty\s+section|orcid"
    r"|correspondence\s*:|graphical\s+abstract|highlights|in\s+brief|abstract|summary|关键词|摘\s*要)",
    re.IGNORECASE,
)
AFFIL_RE = re.compile(
    r"universit|institut|department|dept\.|college|school|laborator|hospital|cent(er|re)\b|faculty"
    r"|academy|klinik|\binc\.|\bltd\b|gmbh|大学|学院|研究所|研究院|医院|实验室|公司|中心",
    re.IGNORECASE,
)
EMAIL_RE = re.compile(
    r"[\w.+-]+@\s?[\w-]+(\.\s?[\w-]+)+|e-?mail|电子邮[箱件]|corresponding\s+author|通[信讯]\s*作者",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[^\W\d_]{2,}")
_NAME_CONNECTORS = frozenset(
    {
        "and",
        "et",
        "al",
        "de",
        "der",
        "den",
        "van",
        "von",
        "la",
        "le",
        "di",
        "da",
        "du",
        "dos",
        "del",
    }
)
FRONT_TEXT_TYPES = (BlockType.PARAGRAPH, BlockType.OTHER)


@dataclass
class RawBlock:
    """引擎无关的中间块。bbox 已是 PDF 点、左上原点。"""

    type: BlockType
    page: int
    bbox: BBox
    # 文本按片段给出：("text", "...") 或 ("math", "latex")；纯文本块可只给 text
    segments: list[tuple[str, str]] = field(default_factory=list)
    text: str = ""
    latex: str | None = None
    html: str | None = None
    level: int | None = None
    label: str | None = None
    image_path: str | None = None  # 引擎导出的图片（相对 raw 目录），可空
    confidence: float | None = None
    flags: list[str] = field(default_factory=list)
    extra_anchors: list[tuple[int, BBox]] = field(default_factory=list)

    def plain_text(self) -> str:
        if self.segments:
            return "".join(s if k == "text" else f"${s}$" for k, s in self.segments)
        return self.text


TABLE_TAGS = frozenset(
    {"table", "thead", "tbody", "tr", "td", "th", "math", "sup", "sub", "b", "i"}
)
_TAG_RE = re.compile(r"<\s*(/?)\s*([a-zA-Z0-9]+)([^>]*)>")
_SPAN_ATTR_RE = re.compile(r"\b(rowspan|colspan)\s*=\s*[\"']?(\d+)[\"']?", re.IGNORECASE)


def sanitize_table_html(html: str | None) -> str | None:
    """只保留 IR 约定的表格标签与 rowspan/colspan 属性（docs/02-document-ir.md §3.6）。"""
    if not html:
        return None

    def repl(m: re.Match) -> str:
        closing, tag, attrs = m.group(1), m.group(2).lower(), m.group(3)
        if tag not in TABLE_TAGS:
            return ""
        if closing:
            return f"</{tag}>"
        kept = (
            "".join(f' {k.lower()}="{v}"' for k, v in _SPAN_ATTR_RE.findall(attrs))
            if tag in ("td", "th")
            else ""
        )
        return f"<{tag}{kept}>"

    out = _TAG_RE.sub(repl, html).strip()
    return out or None


def clean_text(s: str) -> str:
    s = unicodedata.normalize("NFC", s)
    s = s.replace("­", "")  # 软连字符
    return re.sub(r"\s+", " ", s).strip()


def canonical_hash(*parts: str | None) -> str:
    joined = "␞".join(clean_text(p or "") for p in parts)
    return "sha256:" + hashlib.sha256(joined.encode("utf-8")).hexdigest()


def clamp_bbox(b: BBox, w: float, h: float) -> BBox:
    x0, y0, x1, y1 = b
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    return (
        round(max(0.0, min(x0, w)), 2),
        round(max(0.0, min(y0, h)), 2),
        round(max(0.0, min(x1, w)), 2),
        round(max(0.0, min(y1, h)), 2),
    )


def mark_reference_section(blocks: list[RawBlock]) -> None:
    """ "References" 标题之后的段落 / 列表项视为参考文献条目，直到遇到下一个非参考文献类标题。"""
    in_refs = False
    for b in blocks:
        if b.type == BlockType.HEADING:
            in_refs = bool(REFERENCES_HEADING_RE.match(b.plain_text()))
            continue
        if in_refs and b.type in (BlockType.PARAGRAPH, BlockType.LIST_ITEM):
            b.type = BlockType.REFERENCE_ENTRY


def _name_like(t: str) -> bool:
    """作者行：拉丁词多数含大写字母（人名）；纯中文时为不含句号的短行。"""
    if not t or len(t) > 1500:
        return False
    latin = [
        w for w in _WORD_RE.findall(t) if not CJK_RE.search(w) and w.lower() not in _NAME_CONNECTORS
    ]
    if not latin:
        return bool(CJK_RE.search(t)) and len(t) <= 80 and "。" not in t
    caps = sum(1 for w in latin if any(c.isupper() for c in w))
    has_sep = bool(re.search(r",|，|、|&|\band\b|和", t))
    return caps / len(latin) >= 0.6 and (has_sep or len(t) <= 60)


def _long_text(t: str) -> bool:
    return len(t) >= 400 or len(CJK_RE.findall(t)) >= 150


def mark_front_matter(blocks: list[RawBlock], pages: list[tuple[float, float]]) -> None:
    """识别 abstract 与 author_info（只改 paragraph / other 类块，以及被误判为 heading 的作者行）。

    规则（首两页）：
    1. 以 "Abstract" / "摘要" 开头的段落 → abstract；其后紧接的、以小写字母开头的同页段落视为续段。
    2. "Abstract" / "Summary" / "摘要" 标题之后、下一个标题之前的段落 → abstract。
    3. 标题（title）之后：第一个像人名列表的块 → author_info；随后连续的单位 / 邮箱行 → author_info。
       日期、DOI、"Open access" 等跳过；关键词、"Edited by"、正文标题等终止作者区。
    4. "Authors" 标题之后第一个像人名列表的段落 → author_info（Cell 系列的侧栏）。
    5. 作者区之后（同页、正文标题之前）第一个足够长的段落，若较宽（≥ 0.45 页宽）
       或紧跟关键词行 → abstract。
    """
    n = len(blocks)

    def text(i: int) -> str:
        return clean_text(blocks[i].plain_text())

    # 规则 1、2
    i = 0
    while i < n:
        b = blocks[i]
        if b.page > 1:
            break
        t = text(i)
        if b.type == BlockType.PARAGRAPH and ABSTRACT_START_RE.match(t):
            b.type = BlockType.ABSTRACT
            j = i + 1
            while j < n and blocks[j].page == b.page and blocks[j].type == BlockType.PARAGRAPH:
                if not text(j)[:1].islower():
                    break
                blocks[j].type = BlockType.ABSTRACT
                j += 1
            i = j
            continue
        if b.type == BlockType.HEADING and ABSTRACT_HEAD_RE.match(t):
            j, marked = i + 1, 0
            while (
                j < n
                and marked < 4
                and blocks[j].page <= b.page + 1
                and blocks[j].type != BlockType.HEADING
            ):
                bj, tj = blocks[j], text(j)
                w = pages[bj.page][0] if bj.page < len(pages) else 0.0
                if (
                    bj.type == BlockType.PARAGRAPH
                    and not (FRONT_SKIP_RE.match(tj) or FRONT_STOP_RE.match(tj))
                    and bj.bbox[2] - bj.bbox[0] >= w * 0.3  # 侧栏不算
                ):
                    bj.type = BlockType.ABSTRACT
                    marked += 1
                j += 1
            i = j
            continue
        i += 1

    # 规则 4
    for i, b in enumerate(blocks):
        if b.page > 1:
            break
        if b.type == BlockType.HEADING and re.match(r"^\s*authors?\s*$", text(i), re.IGNORECASE):
            for j in range(i + 1, n):
                if blocks[j].type == BlockType.HEADING or blocks[j].page != b.page:
                    break
                if blocks[j].type in FRONT_TEXT_TYPES and _name_like(text(j)):
                    blocks[j].type = BlockType.AUTHOR_INFO
                    break

    # 规则 3
    ti = next((i for i, b in enumerate(blocks) if b.type == BlockType.TITLE and b.page <= 1), None)
    if ti is None or blocks[ti].page >= len(pages):
        return
    page = blocks[ti].page
    w, h = pages[page]
    last_author = None
    for j in range(ti + 1, n):
        b = blocks[j]
        if b.page != page or b.type == BlockType.ABSTRACT or b.bbox[1] > h * 0.6:
            break
        t = text(j)
        if FRONT_STOP_RE.match(t):
            break
        if FRONT_SKIP_RE.match(t) or b.type not in (*FRONT_TEXT_TYPES, BlockType.HEADING):
            continue
        if last_author is None:
            if not _name_like(t):
                break
            # 被判成 heading 的作者行：须带逗号、角标符号或姓名缩写，且不像编号章节标题
            # （避免把紧跟题目的 "Materials and Methods" 当成作者）
            if b.type == BlockType.HEADING and (
                HEADING_NUMBER_RE.match(t) or not re.search(r"[,，、&*∗†‡§]|\b[A-Z]\.|[^\W\d]\d", t)
            ):
                break
        elif b.type == BlockType.HEADING or not (
            AFFIL_RE.search(t) or EMAIL_RE.search(t) or (_name_like(t) and len(t) < 300)
        ):
            break
        b.type, b.level = BlockType.AUTHOR_INFO, None
        last_author = j
    if last_author is None or any(b.type == BlockType.ABSTRACT and b.page == page for b in blocks):
        return

    # 规则 5
    for j in range(last_author + 1, n):
        b = blocks[j]
        if b.page != page:
            break
        t = text(j)
        if b.type == BlockType.HEADING:
            if t.endswith((":", "：")):
                continue  # 侧栏小标题（"Citation:" 等）
            break
        if b.type != BlockType.PARAGRAPH or FRONT_SKIP_RE.match(t) or FRONT_STOP_RE.match(t):
            continue
        width = b.bbox[2] - b.bbox[0]
        if width < w * 0.3:
            continue  # 侧栏
        if _long_text(t):
            nxt = next(
                (
                    text(k)
                    for k in range(j + 1, n)
                    if blocks[k].type in FRONT_TEXT_TYPES and blocks[k].page == page
                ),
                "",
            )
            if width >= w * 0.45 or KEYWORDS_RE.match(nxt):
                b.type = BlockType.ABSTRACT
        break


def merge_continuations(blocks: list[RawBlock], cont: list[bool]) -> list[RawBlock]:
    """cont[i] 为 True 表示 blocks[i] 是上一个同类块的跨栏 / 跨页续段。"""
    out: list[RawBlock] = []
    for b, c in zip(blocks, cont, strict=True):
        if (
            c
            and out
            and out[-1].type == b.type
            and b.type
            in (
                BlockType.PARAGRAPH,
                BlockType.LIST_ITEM,
                BlockType.REFERENCE_ENTRY,
                BlockType.FOOTNOTE,
            )
        ):
            prev = out[-1]
            if prev.segments or b.segments:
                prev.segments = (
                    (prev.segments or [("text", prev.text)])
                    + [("text", " ")]
                    + (b.segments or [("text", b.text)])
                )
            else:
                prev.text = prev.text.rstrip() + " " + b.text.lstrip()
            prev.extra_anchors.append((b.page, b.bbox))
            prev.extra_anchors.extend(b.extra_anchors)
            continue
        out.append(b)
    return out


def _section_id(title: str, used: set[str], counter: list[int]) -> str:
    m = HEADING_NUMBER_RE.match(title)
    sid = "s_" + m.group(1).replace(".", "_") if m else ""
    if not sid or sid in used:
        counter[0] += 1
        sid = f"s_u{counter[0]}"
    used.add(sid)
    return sid


def _caption_target(blocks: list[Block], i: int) -> str | None:
    """为 blocks[i]（caption）找同页最近的 figure / table；优先按标签类型匹配。"""
    cap = blocks[i]
    if not cap.anchors:
        return None
    page = cap.anchors[0].page
    cy0, cy1 = cap.anchors[0].bbox[1], cap.anchors[0].bbox[3]
    want = None
    if cap.label:
        want = (
            BlockType.TABLE
            if re.match(r"(table|表)", cap.label, re.IGNORECASE)
            else BlockType.FIGURE
        )
    best, best_d = None, float("inf")
    for j, b in enumerate(blocks):
        if b.type not in (BlockType.FIGURE, BlockType.TABLE) or not b.anchors:
            continue
        if b.anchors[0].page != page:
            continue
        by0, by1 = b.anchors[0].bbox[1], b.anchors[0].bbox[3]
        d = max(0.0, by0 - cy1, cy0 - by1) + abs(j - i) * 2.0
        if want is not None and b.type != want:
            d += 1000.0
        if d < best_d:
            best, best_d = b.id, d
    return best


def build_document(
    raw_blocks: list[RawBlock],
    *,
    pdf_sha256: str,
    pages: list[tuple[float, float]],
    engine: str,
    engine_version: str,
    meta: Meta | None = None,
    normalizer_version: str = NORMALIZER_VERSION,
    pages_parsed: list[int] | None = None,
) -> tuple[Document, list[str]]:
    """组装并校验 Document。返回 (doc, problems)；问题同时写入对应块的 flags。"""
    mark_front_matter(raw_blocks, pages)
    mark_reference_section(raw_blocks)
    page_infos = [
        PageInfo(index=i, width=round(w, 2), height=round(h, 2)) for i, (w, h) in enumerate(pages)
    ]

    blocks: list[Block] = []
    assets: list[Asset] = []
    sections: list[Section] = []
    references: list[Reference] = []
    used_sids: set[str] = set()
    sid_counter = [0]
    section_stack: list[Section] = []
    cjk = total = 0

    for rb in raw_blocks:
        if not (0 <= rb.page < len(pages)):
            continue
        w, h = pages[rb.page]
        bid = f"b_{len(blocks):04d}"

        text, inlines = "", []
        if rb.segments:
            n_eq = 0
            parts = []
            for kind, s in rb.segments:
                if kind == "math" and s.strip():
                    n_eq += 1
                    key = f"EQ{n_eq}"
                    inlines.append(Inline(key=key, kind=InlineKind.MATH, latex=s.strip()))
                    parts.append(f"⟦{key}⟧")
                else:
                    parts.append(s)
            text = clean_text("".join(parts))
        else:
            text = clean_text(rb.text)
        if rb.type in (BlockType.EQUATION, BlockType.FIGURE, BlockType.TABLE) and not rb.segments:
            text = "" if rb.type != BlockType.TABLE else text

        if rb.type in (BlockType.PARAGRAPH, BlockType.CAPTION, BlockType.LIST_ITEM) and not (
            text or inlines
        ):
            continue  # 空块直接丢弃

        anchors = [Anchor(page=rb.page, bbox=clamp_bbox(rb.bbox, w, h))]
        for p, bb in rb.extra_anchors:
            if 0 <= p < len(pages):
                anchors.append(Anchor(page=p, bbox=clamp_bbox(bb, *pages[p])))

        label = rb.label
        if rb.type == BlockType.CAPTION and label is None:
            m = CAPTION_LABEL_RE.match(text)
            label = clean_text(m.group(1)) if m else None

        asset_id = None
        if rb.type in (BlockType.FIGURE, BlockType.TABLE):
            asset_id = f"a_{len(assets):04d}"
            assets.append(
                Asset(
                    id=asset_id,
                    path=f"assets/{asset_id}.png",
                    page=rb.page,
                    bbox=anchors[0].bbox,
                )
            )

        level = rb.level
        if rb.type == BlockType.HEADING:
            level = max(1, min(4, level or 1))

        section_id = section_stack[-1].id if section_stack else None
        if rb.type == BlockType.HEADING and text:
            while section_stack and section_stack[-1].level >= level:
                section_stack.pop()
            sec = Section(
                id=_section_id(text, used_sids, sid_counter),
                title=text,
                level=level,
                parent_id=section_stack[-1].id if section_stack else None,
                heading_block_id=bid,
            )
            sections.append(sec)
            section_stack.append(sec)
            section_id = sec.id

        blocks.append(
            Block(
                id=bid,
                type=rb.type,
                order=len(blocks),
                section_id=section_id,
                level=level if rb.type in (BlockType.HEADING, BlockType.LIST_ITEM) else None,
                text=text,
                inlines=inlines,
                latex=clean_text(rb.latex) if rb.latex else None,
                html=sanitize_table_html(rb.html) if rb.type == BlockType.TABLE else None,
                asset_id=asset_id,
                label=label,
                anchors=anchors,
                content_hash=canonical_hash(
                    rb.type.value, text, rb.latex, sanitize_table_html(rb.html)
                ),
                confidence=rb.confidence,
                flags=list(rb.flags),
            )
        )
        if rb.type in (BlockType.PARAGRAPH, BlockType.ABSTRACT, BlockType.TITLE, BlockType.HEADING):
            cjk += len(CJK_RE.findall(text))
            total += len(text)

    # 章节 block_range
    by_section: dict[str, list[str]] = {}
    for b in blocks:
        if b.section_id:
            by_section.setdefault(b.section_id, []).append(b.id)
    for s in sections:
        ids = by_section.get(s.id)
        if ids:
            s.block_range = (ids[0], ids[-1])

    # 图注配对
    for i, b in enumerate(blocks):
        if b.type == BlockType.CAPTION:
            b.caption_of = _caption_target(blocks, i)

    # 参考文献
    used_rids: set[str] = set()
    for b in blocks:
        if b.type != BlockType.REFERENCE_ENTRY:
            continue
        m = REF_NUMBER_RE.match(b.text)
        rid = f"r_{int(m.group(1))}" if m else ""
        if not rid or rid in used_rids:
            rid = f"r_x{len(references) + 1}"
        used_rids.add(rid)
        references.append(Reference(id=rid, raw_block_id=b.id))

    meta = meta or Meta()
    if meta.title is None:
        t = next((b.text for b in blocks if b.type == BlockType.TITLE), None)
        meta = meta.model_copy(update={"title": t})
    if meta.language is None and total:
        meta = meta.model_copy(update={"language": "zh" if cjk / total > 0.2 else "en"})

    doc = Document(
        doc_id=doc_id_from_sha256(pdf_sha256),
        source=Source(pdf_sha256=pdf_sha256, page_count=len(pages), pages=page_infos),
        meta=meta,
        parser=ParserInfo(
            engine=engine,
            engine_version=engine_version,
            normalizer_version=normalizer_version,
            created_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            pages_parsed=pages_parsed,
        ),
        sections=sections,
        blocks=blocks,
        references=references,
        assets=assets,
    )
    problems = validate_document(doc)
    by_id = {b.id: b for b in doc.blocks}
    for p in problems:
        bid = p.split(":", 1)[0]
        if bid in by_id and "ir_warning" not in by_id[bid].flags:
            by_id[bid].flags.append("ir_warning")
    return doc, problems
