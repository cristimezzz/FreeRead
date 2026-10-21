"""嵌入任务：块 → chunk → 向量 → sqlite-vec。见 docs/m2/README.md。

任务：
- embed（并发 1，CPU 密集）：一篇文档的 chunk 全部重算并替换；chunk 文本没变的直接复用旧向量，
  所以重新解析（快速 → 高质量）后只算真正变了的部分；
- model_download（并发 1）：下载内置嵌入模型，完成后给所有待嵌入的文档排队。

嵌入来源由设置 embedding.source 决定：内置本地模型（默认），或 routes["embed"] 指定的服务。
后者要发送文档内容，和翻译一样需要用户确认过该 provider（architecture §10）。
换来源 / 模型后向量不可混用：索引整体清空，所有文档重新排队（enqueue_missing）。
"""

import asyncio
import logging
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

import httpx
from pydantic import BaseModel
from sqlalchemy import Engine, delete, select, update

from freeread.config import DataPaths
from freeread.infra.db.engine import SessionFactory
from freeread.infra.db.models import BlockRow, DocumentRow, EmbeddingChunkRow, JobRow
from freeread.infra.embedding.local import LocalEmbedder
from freeread.infra.embedding.registry import MODELS, LocalModelSpec
from freeread.infra.jobs.events import EventBus
from freeread.infra.jobs.queue import JobOut, JobQueue, JobStatus
from freeread.infra.jobs.worker import JobContext
from freeread.infra.llm.default_gateway import DefaultGateway
from freeread.infra.llm.errors import RouteNotConfigured
from freeread.infra.llm.gateway import TaskKind
from freeread.infra.search.chunker import Chunk, TokenLen, approx_tokens, build_chunks
from freeread.infra.search.vector_index import SqliteVecIndex, VectorIndex
from freeread.services.doc_blocks import DocumentNotReady, load_doc
from freeread.services.settings import SettingsService

log = logging.getLogger(__name__)

PROVIDER_BATCH = 64
DOWNLOAD_TIMEOUT = httpx.Timeout(30.0, read=120.0)
Kind = Literal["passage", "query"]
NotReadyCode = Literal[
    "model_not_downloaded", "unknown_model", "route_not_configured", "missing_api_key",
    "consent_required",
]  # fmt: skip


class EmbedNotReady(RuntimeError):
    def __init__(self, code: NotReadyCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class Backend:
    """当前设置下的嵌入来源。key 写进 embedding_chunks.model 与索引状态。"""

    key: str
    embed: Callable[[list[str], Kind], Awaitable[list[list[float]]]]
    token_len: TokenLen


class EmbeddingStatus(BaseModel):
    source: Literal["local", "provider"]
    model_key: str | None
    ready: bool
    not_ready: NotReadyCode | None = None
    message: str | None = None
    # 本地模型
    local_model: str | None = None
    local_label: str | None = None
    downloaded: bool = False
    size_bytes: int = 0
    downloaded_bytes: int = 0
    download_job: JobOut | None = None
    # 索引
    index_model: str | None = None
    index_dim: int | None = None
    docs_total: int = 0
    docs_embedded: int = 0


class EmbedService:
    def __init__(
        self,
        sessions: SessionFactory,
        paths: DataPaths,
        jobs: JobQueue,
        bus: EventBus,
        settings: SettingsService,
        gateway: DefaultGateway,
        index: VectorIndex | None = None,
        engine: Engine | None = None,
    ) -> None:
        self._engine = engine
        self._sessions = sessions
        self._paths = paths
        self._jobs = jobs
        self._bus = bus
        self._settings = settings
        self._gateway = gateway
        self.index = index or SqliteVecIndex()
        self._embedders: dict[str, LocalEmbedder] = {}
        self._lock = threading.Lock()  # 索引清空 / 重排队与写向量互斥
        # 一篇文档嵌入完成后调用（图谱自动抽取挂在这里）
        self.on_embedded: Callable[[str], object] | None = None

    # ------------------------------------------------------------ 来源

    def local_embedder(self, model_id: str | None = None) -> LocalEmbedder:
        model_id = model_id or self._settings.get().embedding.local_model
        spec: LocalModelSpec | None = MODELS.get(model_id)
        if spec is None:
            raise EmbedNotReady("unknown_model", f"未知的内置嵌入模型 {model_id!r}")
        if model_id not in self._embedders:
            self._embedders[model_id] = LocalEmbedder(spec, self._paths.models)
        return self._embedders[model_id]

    def backend(self) -> Backend:
        """检查当前来源是否可用，不可用时抛 EmbedNotReady。"""
        settings = self._settings.get()
        if settings.embedding.source == "local":
            embedder = self.local_embedder(settings.embedding.local_model)
            if not embedder.is_downloaded():
                raise EmbedNotReady("model_not_downloaded", "内置嵌入模型尚未下载")

            async def embed_local(texts: list[str], kind: Kind) -> list[list[float]]:
                return await asyncio.to_thread(embedder.embed, texts, kind)

            return Backend(embedder.spec.key, embed_local, embedder.token_len)

        try:
            provider_id, model = self._gateway.route(TaskKind.EMBED)
        except RouteNotConfigured as e:
            raise EmbedNotReady("route_not_configured", "未配置嵌入使用的服务和模型") from e
        provider = next((p for p in settings.providers if p.id == provider_id), None)
        if provider is None:
            raise EmbedNotReady("route_not_configured", f"provider {provider_id!r} 不存在")
        if provider.kind != "ollama" and not self._gateway.secrets.has(provider_id):
            raise EmbedNotReady("missing_api_key", f"provider {provider_id!r} 没有 API Key")
        if provider_id not in settings.consented_providers:
            raise EmbedNotReady("consent_required", f"向 {provider.name} 发送文档内容前需要确认")

        async def embed_remote(texts: list[str], _kind: Kind) -> list[list[float]]:
            out: list[list[float]] = []
            for start in range(0, len(texts), PROVIDER_BATCH):
                out += await self._gateway.embed(texts[start : start + PROVIDER_BATCH])
            return out

        return Backend(f"{provider_id}/{model}", embed_remote, approx_tokens)

    def try_backend(self) -> Backend | None:
        try:
            return self.backend()
        except EmbedNotReady:
            return None

    async def embed_query(self, query: str) -> tuple[str, list[float]] | None:
        backend = self.try_backend()
        if backend is None:
            return None
        [vector] = await backend.embed([query], "query")
        return backend.key, vector

    # ------------------------------------------------------------ 状态

    def status(self) -> EmbeddingStatus:
        settings = self._settings.get().embedding
        out = EmbeddingStatus(source=settings.source, model_key=None, ready=False)
        try:
            out.model_key = self.backend().key
            out.ready = True
        except EmbedNotReady as e:
            out.not_ready, out.message = e.code, str(e)
        if settings.source == "local" and settings.local_model in MODELS:
            embedder = self.local_embedder(settings.local_model)
            out.model_key = out.model_key or embedder.spec.key
            out.local_model = embedder.spec.id
            out.local_label = embedder.spec.label
            out.downloaded = embedder.is_downloaded()
            out.size_bytes = embedder.spec.size
            out.downloaded_bytes = embedder.downloaded_bytes()
        out.download_job = self._active_job("model_download")
        with self._sessions() as s:
            state = self.index.state(s)
            if state:
                out.index_model, out.index_dim = state.model, state.dim
            out.docs_total = len(
                s.scalars(
                    select(DocumentRow.doc_id).where(DocumentRow.parse_status == "ready")
                ).all()
            )
            out.docs_embedded = len(
                s.scalars(
                    select(DocumentRow.doc_id).where(DocumentRow.embed_status == "ready")
                ).all()
            )
        return out

    def _active_job(self, kind: str, doc_id: str | None = None, statuses=None) -> JobOut | None:
        statuses = statuses or [JobStatus.QUEUED, JobStatus.RUNNING]
        with self._sessions() as s:
            q = select(JobRow.id).where(JobRow.kind == kind, JobRow.status.in_(statuses))
            if doc_id is not None:
                q = q.where(JobRow.payload["doc_id"].as_string() == doc_id)
            job_id = s.scalar(q.order_by(JobRow.created_at.desc()))
        return self._jobs.get(job_id) if job_id else None

    # ------------------------------------------------------------ 排队

    def enqueue_embed(self, doc_id: str, *, force: bool = False) -> JobOut | None:
        """解析完成后调用。来源不可用或关闭了自动嵌入（force=False 时）就不排队。

        只和排队中的任务去重：正在运行的任务读的可能是旧块，新解析完成后要再算一次。
        """
        if not force and not self._settings.get().embedding.auto:
            return None
        if self.try_backend() is None:
            return None
        existing = self._active_job("embed", doc_id, [JobStatus.QUEUED])
        if existing:
            return existing
        return self._jobs.enqueue("embed", {"doc_id": doc_id})

    def enqueue_missing(self) -> list[str]:
        """启动、设置变更、模型下载完成后调用：来源 / 模型变了就清空索引，然后给未嵌入的文档排队。"""
        backend = self.try_backend()
        if backend is None:
            return []
        with self._lock, self._sessions.begin() as s:
            state = self.index.state(s)
            if state is not None and state.model != backend.key:
                log.info(
                    "embedding model changed %s → %s; clearing index", state.model, backend.key
                )
                self._clear_all(s)
            docs = s.scalars(
                select(DocumentRow.doc_id).where(
                    DocumentRow.parse_status == "ready", DocumentRow.embed_status != "ready"
                )
            ).all()
        try:
            self.index.drop_unused(self._engine) if self._engine is not None else None
        except Exception:  # 清理失败不影响使用，空表下次再删
            log.warning("failed to drop unused vector tables", exc_info=True)
        return [job.id for d in docs if (job := self.enqueue_embed(d, force=True))]

    def rebuild(self) -> list[str]:
        """清空索引，所有文档重新嵌入。"""
        self.backend()  # 不可用时直接报错，免得清空后没法重建
        with self._lock, self._sessions.begin() as s:
            self._clear_all(s)
        return self.enqueue_missing()

    def _clear_all(self, s) -> None:
        self.index.clear(s)
        s.execute(delete(EmbeddingChunkRow))
        s.execute(update(DocumentRow).values(embed_status="pending"))

    def request_download(self) -> JobOut:
        existing = self._active_job("model_download")
        if existing:
            return existing
        embedder = self.local_embedder()
        return self._jobs.enqueue("model_download", {"model": embedder.spec.id})

    # ------------------------------------------------------------ 任务

    async def run_model_download_job(self, ctx: JobContext) -> None:
        embedder = self.local_embedder(ctx.job.payload.get("model"))
        mirror = self._settings.get().embedding.mirror

        async def progress(done: int, total: int) -> None:
            mb = 1 << 20
            await ctx.report(done / total if total else 0, f"{done / mb:.0f} / {total / mb:.0f} MB")

        async with httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT) as client:
            await embedder.download(client, mirror, progress)
        await ctx.report(1.0, f"{embedder.spec.label} 已就绪")
        queued = await asyncio.to_thread(self.enqueue_missing)
        if queued:
            log.info("queued %d embed jobs after model download", len(queued))

    async def run_embed_job(self, ctx: JobContext) -> None:
        doc_id = ctx.job.payload["doc_id"]
        backend = self.backend()
        await asyncio.to_thread(self._set_status, doc_id, "embedding")
        try:
            n_chunks, n_new = await self._embed(doc_id, backend, ctx)
        except BaseException:
            await asyncio.to_thread(self._set_status, doc_id, "failed")
            raise
        await ctx.report(1.0, f"{n_chunks} 个片段，新计算 {n_new}")
        if self.on_embedded:
            try:
                await asyncio.to_thread(self.on_embedded, doc_id)
            except Exception:  # 后续任务排队失败不影响嵌入本身
                log.warning("on_embedded hook failed for %s", doc_id, exc_info=True)

    async def _embed(self, doc_id: str, backend: Backend, ctx: JobContext) -> tuple[int, int]:
        blocks, titles = await asyncio.to_thread(self._load_blocks, doc_id)
        chunks = await asyncio.to_thread(build_chunks, blocks, titles, backend.token_len)
        reuse = await asyncio.to_thread(self._reusable, doc_id, backend.key, chunks)
        todo = [c for c in chunks if c.text_hash not in reuse]

        fresh: dict[str, list[float]] = {}
        step = 32
        for start in range(0, len(todo), step):
            part = todo[start : start + step]
            vectors = await backend.embed([c.text for c in part], "passage")
            fresh.update((c.text_hash, v) for c, v in zip(part, vectors, strict=True))
            await ctx.report(0.05 + 0.9 * (start + len(part)) / len(todo), "计算嵌入")
        await asyncio.to_thread(self._store, doc_id, backend.key, chunks, reuse | fresh)
        return len(chunks), len(todo)

    def _load_blocks(self, doc_id: str) -> tuple[list[BlockRow], dict[str, str]]:
        try:
            doc = load_doc(self._sessions, self._paths, doc_id)
        except DocumentNotReady as e:
            raise RuntimeError(str(e)) from e
        return doc.blocks, doc.section_titles

    def _reusable(self, doc_id: str, model: str, chunks: list[Chunk]) -> dict[str, list[float]]:
        hashes = {c.text_hash for c in chunks}
        with self._sessions() as s:
            rows = s.execute(
                select(EmbeddingChunkRow.rowid, EmbeddingChunkRow.text_hash).where(
                    EmbeddingChunkRow.doc_id == doc_id, EmbeddingChunkRow.model == model
                )
            ).all()
            by_rowid = {r: h for r, h in rows if h in hashes}
            vectors = self.index.vectors(s, list(by_rowid))
        return {by_rowid[r]: v for r, v in vectors.items()}

    def _store(
        self, doc_id: str, model: str, chunks: list[Chunk], vectors: dict[str, list[float]]
    ) -> None:
        with self._lock, self._sessions.begin() as s:
            if vectors:
                self.index.ensure(s, model, len(next(iter(vectors.values()))))
            self.index.delete_doc(s, doc_id)
            s.execute(delete(EmbeddingChunkRow).where(EmbeddingChunkRow.doc_id == doc_id))
            rows = [
                EmbeddingChunkRow(
                    doc_id=doc_id,
                    ord=c.ord,
                    block_ids=c.block_ids,
                    model=model,
                    text_hash=c.text_hash,
                    text=c.text,
                )
                for c in chunks
            ]
            s.add_all(rows)
            s.flush()
            self.index.upsert(s, doc_id, [(r.rowid, vectors[r.text_hash]) for r in rows])
            s.execute(
                update(DocumentRow).where(DocumentRow.doc_id == doc_id).values(embed_status="ready")
            )
        self._publish(doc_id)

    def _set_status(self, doc_id: str, status: str) -> None:
        with self._sessions.begin() as s:
            s.execute(
                update(DocumentRow).where(DocumentRow.doc_id == doc_id).values(embed_status=status)
            )
        self._publish(doc_id)

    def _publish(self, doc_id: str) -> None:
        from freeread.services.parse import DocumentOut

        with self._sessions() as s:
            row = s.get(DocumentRow, doc_id)
            if row is not None:
                self._bus.publish(
                    "document", DocumentOut.model_validate(row).model_dump(mode="json")
                )
