"""混合检索：FTS5 关键词 + sqlite-vec 语义，RRF 融合为块级结果。见 docs/01-architecture.md §5.7。

嵌入来源不可用、文档还没嵌入或索引属于别的模型时只走关键词，响应的 modes 会说明。
以后的总结 / 问答通过 search_document 取上下文，每条命中都带 doc_id#block_id。
"""

import asyncio
import logging
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select

from freeread.infra.db.engine import SessionFactory
from freeread.infra.db.models import BlockRow, DocumentRow, EmbeddingChunkRow
from freeread.infra.search import fts
from freeread.infra.search.hybrid import rrf_merge
from freeread.infra.search.text import block_plain_text
from freeread.services.embed import EmbedService

log = logging.getLogger(__name__)

CANDIDATES = 50
Mode = Literal["fts", "vector"]


class SearchHit(BaseModel):
    doc_id: str
    block_id: str
    type: str
    page: int | None
    score: float
    sources: list[Mode]
    # 高亮片段：命中词前后为 \x02 / \x03
    snippet: str


class SearchResponse(BaseModel):
    query: str
    modes: list[Mode]
    hits: list[SearchHit]


class SearchService:
    def __init__(self, sessions: SessionFactory, embed: EmbedService) -> None:
        self._sessions = sessions
        self._embed = embed

    async def search_document(self, doc_id: str, query: str, k: int = 20) -> SearchResponse:
        query = query.strip()
        if not query:
            return SearchResponse(query=query, modes=[], hits=[])
        semantic = await self._semantic_ready(doc_id)
        q_vec = None
        if semantic:
            try:
                q_vec = await self._embed.embed_query(query)
            except Exception:  # 嵌入服务出错时退回纯关键词，不让搜索整个失败
                log.warning("query embedding failed; falling back to keyword search", exc_info=True)
        return await asyncio.to_thread(self._search, doc_id, query, q_vec, k)

    async def _semantic_ready(self, doc_id: str) -> bool:
        def check() -> bool:
            with self._sessions() as s:
                return s.scalar(
                    select(DocumentRow.embed_status).where(DocumentRow.doc_id == doc_id)
                ) in ("ready", "embedding")  # 重新嵌入期间旧向量仍可用

        return await asyncio.to_thread(check)

    def _search(
        self, doc_id: str, query: str, q_vec: tuple[str, list[float]] | None, k: int
    ) -> SearchResponse:
        with self._sessions() as s:
            if s.get(DocumentRow, doc_id) is None:
                raise LookupError(f"文档 {doc_id} 不存在")
            fts_hits = fts.search(s, query, doc_id, CANDIDATES)
            rankings: dict[str, list[str]] = {"fts": [h.block_id for h in fts_hits]}
            modes: list[Mode] = ["fts"]

            state = self._embed.index.state(s)
            if q_vec is not None and state is not None and state.model == q_vec[0]:
                vec_hits = self._embed.index.knn(s, q_vec[1], CANDIDATES, doc_id)
                chunk_blocks = dict(
                    s.execute(
                        select(EmbeddingChunkRow.rowid, EmbeddingChunkRow.block_ids).where(
                            EmbeddingChunkRow.rowid.in_([h.chunk_rowid for h in vec_hits])
                        )
                    ).all()
                )
                rankings["vector"] = [
                    b for h in vec_hits for b in chunk_blocks.get(h.chunk_rowid, [])
                ]
                modes.append("vector")

            merged = rrf_merge(rankings)[:k]
            blocks = {
                b.block_id: b
                for b in s.scalars(
                    select(BlockRow).where(
                        BlockRow.doc_id == doc_id,
                        BlockRow.block_id.in_([key for key, _, _ in merged]),
                    )
                )
            }
        snippets = {h.block_id: h.snippet for h in fts_hits}
        terms = fts.query_terms(query)
        hits = []
        for block_id, score, sources in merged:
            b = blocks.get(block_id)
            if b is None:  # 块在嵌入之后被重新解析替换了
                continue
            snippet = snippets.get(block_id) or fts.highlight(
                block_plain_text(b.type, b.text, b.inlines, b.html), terms
            )
            hits.append(
                SearchHit(
                    doc_id=doc_id,
                    block_id=block_id,
                    type=b.type,
                    page=b.anchors[0]["page"] if b.anchors else None,
                    score=score,
                    sources=sources,
                    snippet=snippet,
                )
            )
        return SearchResponse(query=query, modes=modes, hits=hits)
