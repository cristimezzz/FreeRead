"""块级全文索引 blocks_fts（FTS5，trigram 分词）。

trigram 对中文不需要分词，按子串匹配；代价是少于 3 个字符的词搜不到，这种查询退回 LIKE。
表在迁移 0002 中创建，由 ParseService 在替换 blocks 的同一事务里维护。
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from freeread.infra.search.text import block_plain_text

MIN_TRIGRAM = 3
HL_START, HL_END = "\x02", "\x03"  # 高亮标记（STX / ETX），正文里不会出现；前端据此加粗
# 空白、引号和中文标点分词；英文标点只从词的两端去掉（保留 0.95、e.g. 这类词内的点）
_TERM_RE = re.compile(r"[^\s\"“”‘’，。；：！？、（）]+")
_EDGE_PUNCT = "'.,;:!?()[]{}"
# 问句里的虚词只会让关键词路命中一堆无关段落（语义路负责理解问句）
STOPWORDS = frozenset(
    {"a", "an", "and", "are", "as", "at", "be", "by", "can", "did", "do", "does", "for", "from",
     "how", "in", "is", "it", "of", "on", "or", "that", "the", "this", "to", "was", "were",
     "what", "when", "where", "which", "who", "why", "will", "with"}
)  # fmt: skip

CREATE_SQL = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS blocks_fts USING fts5("
    "text, doc_id UNINDEXED, block_id UNINDEXED, tokenize='trigram')"
)


@dataclass
class FtsHit:
    doc_id: str
    block_id: str
    snippet: str
    score: float  # 越大越相关


def replace_doc(s: Session, doc_id: str, blocks: Iterable) -> int:
    """blocks 的元素需有 id / block_id、type、text、inlines、html 属性（IR Block 或 BlockRow）。"""
    s.execute(text("DELETE FROM blocks_fts WHERE doc_id = :d"), {"d": doc_id})
    rows = []
    for b in blocks:
        type_ = getattr(b.type, "value", b.type)
        inlines = [
            il if isinstance(il, dict) else il.model_dump(mode="json") for il in (b.inlines or [])
        ]
        body = block_plain_text(type_, b.text or "", inlines, b.html)
        if body:
            rows.append({"t": body, "d": doc_id, "b": getattr(b, "block_id", None) or b.id})
    if rows:
        s.execute(text("INSERT INTO blocks_fts(text, doc_id, block_id) VALUES (:t, :d, :b)"), rows)
    return len(rows)


def delete_doc(s: Session, doc_id: str) -> None:
    s.execute(text("DELETE FROM blocks_fts WHERE doc_id = :d"), {"d": doc_id})


def query_terms(query: str) -> list[str]:
    terms = [t for t in (m.strip(_EDGE_PUNCT) for m in _TERM_RE.findall(query)) if t]
    content = [t for t in terms if t.lower() not in STOPWORDS]
    return content or terms


def _quote(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


def search(s: Session, query: str, doc_id: str | None = None, k: int = 50) -> list[FtsHit]:
    terms = query_terms(query)
    long_terms = [t for t in terms if len(t) >= MIN_TRIGRAM]
    if not terms:
        return []
    if not long_terms:
        return _search_like(s, terms, doc_id, k)
    where = "blocks_fts MATCH :q" + (" AND doc_id = :d" if doc_id else "")
    # 不用 FTS5 的 snippet()：trigram 分词下它按三字组计长度，片段很短，还会把高亮截在词中间
    rows = s.execute(
        text(
            "SELECT doc_id, block_id, text, bm25(blocks_fts) "
            f"FROM blocks_fts WHERE {where} ORDER BY bm25(blocks_fts) LIMIT :k"
        ),
        {"q": " OR ".join(_quote(t) for t in long_terms), "d": doc_id, "k": k},
    ).all()
    # bm25() 越小越相关
    return [FtsHit(d, b, highlight(body, terms), -score) for d, b, body, score in rows]


def _search_like(s: Session, terms: list[str], doc_id: str | None, k: int) -> list[FtsHit]:
    conds = " AND ".join(f"text LIKE :t{i} ESCAPE '\\'" for i in range(len(terms)))
    params: dict = {
        f"t{i}": "%" + t.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        for i, t in enumerate(terms)
    }
    if doc_id:
        conds += " AND doc_id = :d"
        params["d"] = doc_id
    rows = s.execute(
        text(f"SELECT doc_id, block_id, text FROM blocks_fts WHERE {conds} LIMIT :k"),
        params | {"k": k},
    ).all()
    return [FtsHit(d, b, highlight(body, terms), 1.0) for d, b, body in rows]


def highlight(body: str, terms: list[str], width: int = 160) -> str:
    """在 body 里找第一个命中词，截取前后文并给窗口内所有命中词加高亮标记。"""
    lower = body.lower()
    pos = min((p for t in terms if (p := lower.find(t.lower())) >= 0), default=-1)
    if pos < 0:
        return body[:width] + ("…" if len(body) > width else "")
    start = max(0, pos - width // 3)
    snippet = body[start : start + width]
    pattern = "|".join(re.escape(t) for t in sorted(set(terms), key=len, reverse=True))
    snippet = re.sub(
        pattern, lambda m: HL_START + m.group(0) + HL_END, snippet, flags=re.IGNORECASE
    )
    return ("…" if start else "") + snippet + ("…" if start + width < len(body) else "")
