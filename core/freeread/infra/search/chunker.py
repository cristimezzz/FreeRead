"""把文档块切成嵌入用的 chunk。

- 只取可检索的块（search.text.SEARCHABLE_TYPES）；标题块（heading）不单独成 chunk，
  而是作为所在 section 的标题加在每个 chunk 前面，给短段落补上下文；
- 同一 section 内相邻的短块合并，直到约 TARGET_TOKENS；
- 超过 MAX_TOKENS 的块按句子拆开，仍然过长的句子按长度硬切。
每个 chunk 记录覆盖的 block_ids，检索命中后据此回到块。
"""

import hashlib
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

from freeread.domain.ir.models import BlockType
from freeread.infra.search.text import block_plain_text

TARGET_TOKENS = 256
MAX_TOKENS = 480

TokenLen = Callable[[str], int]

_SENTENCE_RE = re.compile(r"(?<=[.!?;])\s+|(?<=[。！？；])")


@dataclass
class Chunk:
    ord: int
    block_ids: list[str]
    text: str
    text_hash: str = field(init=False)

    def __post_init__(self) -> None:
        self.text_hash = hashlib.sha256(self.text.encode("utf-8")).hexdigest()


def approx_tokens(text: str) -> int:
    """没有分词器时的粗估：CJK 字符按 1 个 token，其余按 4 个字符 1 个 token。"""
    cjk = sum(1 for ch in text if "　" <= ch <= "鿿" or "가" <= ch <= "힯")
    return cjk + (len(text) - cjk + 3) // 4


def _split_long(body: str, token_len: TokenLen) -> list[str]:
    pieces: list[str] = []
    buf = ""
    for sent in (p for p in _SENTENCE_RE.split(body) if p.strip()):
        cand = f"{buf} {sent}".strip() if buf else sent
        if token_len(cand) <= TARGET_TOKENS:
            buf = cand
            continue
        if buf:
            pieces.append(buf)
        if token_len(sent) <= MAX_TOKENS:
            buf = sent
        else:
            # 没有句末标点的超长文本（如表格）：按字符硬切
            step = max(1, len(sent) * TARGET_TOKENS // token_len(sent))
            pieces.extend(sent[i : i + step] for i in range(0, len(sent), step))
            buf = ""
    if buf:
        pieces.append(buf)
    return pieces


def build_chunks(
    blocks: Iterable,
    section_titles: Mapping[str, str],
    token_len: TokenLen = approx_tokens,
) -> list[Chunk]:
    """blocks 按阅读顺序给出，元素需有 block_id / id、type、section_id、text、inlines、html。"""
    chunks: list[Chunk] = []
    cur_ids: list[str] = []
    cur_parts: list[str] = []
    cur_tokens = 0
    cur_section: str | None = None

    def emit(ids: list[str], body: str, section: str | None) -> None:
        title = section_titles.get(section or "", "")
        text = f"{title}\n{body}" if title and title != body else body
        chunks.append(Chunk(len(chunks), ids, text))

    def flush() -> None:
        nonlocal cur_ids, cur_parts, cur_tokens
        if cur_ids:
            emit(cur_ids, "\n".join(cur_parts), cur_section)
        cur_ids, cur_parts, cur_tokens = [], [], 0

    for b in blocks:
        type_ = getattr(b.type, "value", b.type)
        if type_ == BlockType.HEADING.value:
            continue
        inlines = [
            il if isinstance(il, dict) else il.model_dump(mode="json") for il in (b.inlines or [])
        ]
        body = block_plain_text(type_, b.text or "", inlines, b.html)
        if not body:
            continue
        block_id = getattr(b, "block_id", None) or b.id
        n = token_len(body)
        if b.section_id != cur_section or cur_tokens + n > TARGET_TOKENS:
            flush()
            cur_section = b.section_id
        if n > MAX_TOKENS:
            flush()
            for piece in _split_long(body, token_len):
                emit([block_id], piece, b.section_id)
            continue
        cur_ids.append(block_id)
        cur_parts.append(body)
        cur_tokens += n
    flush()
    return chunks
