"""解析任务链：PDF → 引擎原生输出 → Normalizer → Document IR → 入库。见 docs/01-architecture.md §5.2。

任务：
- parse（快速模式，并发 2）：PyMuPDF 秒级出可读 IR；完成后按设置追加 parse_hq；
- parse_hq（高质量引擎，全局并发 1，避免显存争用）：MinerU / Docling 升级 IR。
重新解析时按 IR §8 迁移块 ID，译文跟着新块走，无法映射的标记 stale。
原生输出保存在 documents/<doc_id>/raw/<engine>/，已有完整输出（engine.json）时只重新规范化。
"""

import asyncio
import json
import logging
import shutil
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, select, update

from freeread.config import DataPaths
from freeread.domain.ir.migrate import BlockRef, map_blocks
from freeread.domain.ir.models import IR_SCHEMA_VERSION, Document
from freeread.infra.db.engine import SessionFactory
from freeread.infra.db.models import (
    AttachmentRow,
    BlockRow,
    DocumentRow,
    ItemRow,
    JobRow,
    TranslationRow,
)
from freeread.infra.jobs.events import EventBus
from freeread.infra.jobs.queue import JobOut, JobQueue, JobStatus
from freeread.infra.jobs.worker import JobContext
from freeread.infra.parsers.base import RawLayout
from freeread.infra.parsers.registry import EngineSpec, ParserRegistry
from freeread.services.settings import SettingsService

log = logging.getLogger(__name__)

ASSET_DPI = 150
Progress = Callable[[float, str | None], Awaitable[None]]


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    doc_id: str
    page_count: int | None
    parse_status: str  # pending | parsing | ready | failed
    parser_engine: str | None
    parser_version: str | None
    normalizer_version: str | None
    ir_schema_version: str | None
    language: str | None
    updated_at: str


class EngineOut(BaseModel):
    name: str
    label: str
    available: bool
    heavy: bool


class EngineUnavailableError(RuntimeError):
    pass


@dataclass
class ParseOutcome:
    status: Literal["parsed", "renormalized", "cached", "skipped"]
    blocks: int = 0
    migrated: int = 0
    stale: int = 0
    problems: int = 0

    def summary(self) -> str:
        if self.status in ("cached", "skipped"):
            return {"cached": "已是最新解析结果", "skipped": "已有更高质量的解析结果"}[self.status]
        msg = f"{self.blocks} 个块"
        if self.migrated or self.stale:
            msg += f"，译文迁移 {self.migrated}、失效 {self.stale}"
        if self.problems:
            msg += f"，{self.problems} 处 IR 警告"
        return msg


@dataclass
class _DocInfo:
    doc_id: str
    pdf_sha256: str
    parse_status: str
    parser_engine: str | None
    normalizer_version: str | None
    pdf: Path


class ParseService:
    def __init__(
        self,
        sessions: SessionFactory,
        paths: DataPaths,
        jobs: JobQueue,
        bus: EventBus,
        settings: SettingsService,
        registry: ParserRegistry,
    ) -> None:
        self._sessions = sessions
        self._paths = paths
        self._jobs = jobs
        self._bus = bus
        self._settings = settings
        self.registry = registry
        # parse 与 parse_hq 是两种任务、可以同时运行；同一文档的解析必须串行，
        # 否则会同时写 raw/、assets/、ir.json 和 blocks 表
        self._doc_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    # ------------------------------------------------------------ 查询

    def get(self, doc_id: str) -> DocumentOut | None:
        with self._sessions() as s:
            row = s.get(DocumentRow, doc_id)
            return DocumentOut.model_validate(row) if row else None

    def engines(self) -> list[EngineOut]:
        return [
            EngineOut(name=e.name, label=e.label, available=e.available(), heavy=e.heavy)
            for e in self.registry.engines.values()
        ]

    def ir_path(self, doc_id: str) -> Path:
        return self._paths.document_dir(doc_id) / "ir.json"

    def asset_path(self, doc_id: str, name: str) -> Path:
        return self._paths.document_dir(doc_id) / "assets" / name

    def pdf_path(self, doc_id: str) -> Path | None:
        with self._sessions() as s:
            paths = s.scalars(select(AttachmentRow.path).where(AttachmentRow.doc_id == doc_id))
            return next((Path(p) for p in paths if Path(p).is_file()), None)

    # ------------------------------------------------------------ 任务

    def request_parse(self, doc_id: str, engine: str | None = None) -> JobOut:
        """用户手动（重新）解析。engine 为空时走默认链（快速模式 → 按设置升级）。"""
        if engine is None:
            return self._jobs.enqueue("parse", {"doc_id": doc_id, "force": True})
        spec = self.registry.get(engine)
        if not spec.available():
            raise EngineUnavailableError(f"解析引擎 {engine} 未安装")
        kind = "parse_hq" if spec.heavy else "parse"
        return self._jobs.enqueue(kind, {"doc_id": doc_id, "engine": engine, "force": True})

    async def run_parse_job(self, ctx: JobContext) -> None:
        p = ctx.job.payload
        engine = p.get("engine") or "pymupdf"
        outcome = await self.run(p["doc_id"], engine, ctx.report, force=p.get("force", False))
        await ctx.report(1.0, outcome.summary())
        if "engine" not in p:
            await asyncio.to_thread(self._chain_hq, p["doc_id"])

    async def run_parse_hq_job(self, ctx: JobContext) -> None:
        p = ctx.job.payload
        outcome = await self.run(p["doc_id"], p["engine"], ctx.report, force=p.get("force", False))
        await ctx.report(1.0, outcome.summary())

    def _chain_hq(self, doc_id: str) -> JobOut | None:
        """快速解析完成后，按设置追加高质量解析。"""
        choice = self._settings.get().parse_engine
        engine = "mineru" if choice == "auto" else choice
        spec = self.registry.get(engine)
        if not spec.heavy or not spec.available():
            return None
        with self._sessions() as s:
            pending = s.scalar(
                select(JobRow.id).where(
                    JobRow.kind == "parse_hq",
                    JobRow.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
                    JobRow.payload["doc_id"].as_string() == doc_id,
                )
            )
        if pending:
            return None
        return self._jobs.enqueue("parse_hq", {"doc_id": doc_id, "engine": engine})

    # ------------------------------------------------------------ 解析

    async def run(
        self, doc_id: str, engine: str, progress: Progress, force: bool = False
    ) -> ParseOutcome:
        async with self._doc_locks[doc_id]:
            return await self._run_locked(doc_id, engine, progress, force)

    async def _run_locked(
        self, doc_id: str, engine: str, progress: Progress, force: bool
    ) -> ParseOutcome:
        spec = self.registry.get(engine)
        if not spec.available():
            raise EngineUnavailableError(f"解析引擎 {engine} 未安装")
        info = await asyncio.to_thread(self._load, doc_id)

        if not force and info.parse_status == "ready" and info.parser_engine:
            current = self.registry.engines.get(info.parser_engine)
            if info.parser_engine == engine and info.normalizer_version == spec.normalizer.version:
                return ParseOutcome("cached")
            if current is not None and current.rank > spec.rank:
                return ParseOutcome("skipped")

        had_ir = info.parse_status == "ready"
        if not had_ir:
            await asyncio.to_thread(self._set_status, doc_id, "parsing")
        try:
            return await self._parse(info, spec, progress, force)
        except BaseException:
            # 已有可读 IR 时升级失败不影响阅读；第一次解析失败才标记 failed
            await asyncio.to_thread(self._set_status, doc_id, "ready" if had_ir else "failed")
            raise

    async def _parse(
        self, info: _DocInfo, spec: EngineSpec, progress: Progress, force: bool
    ) -> ParseOutcome:
        doc_dir = self._paths.document_dir(info.doc_id)
        raw_dir = doc_dir / "raw" / spec.name
        marker = raw_dir / "engine.json"
        if force or not marker.is_file():
            if raw_dir.exists():
                shutil.rmtree(raw_dir)
            pending: list[asyncio.Future] = []

            def on_progress(p: float, msg: str) -> None:
                pending.append(asyncio.ensure_future(progress(0.05 + 0.75 * p, msg)))

            await progress(0.05, f"{spec.label}：解析中")
            raw = await spec.make_parser().parse(info.pdf, raw_dir, on_progress)
            await asyncio.gather(*pending)
            status = "parsed"
        else:
            engine_info = json.loads(marker.read_text(encoding="utf-8"))
            raw = RawLayout(spec.name, engine_info.get("engine_version", "unknown"), raw_dir, None)
            status = "renormalized"

        await progress(0.85, "规范化为 IR")
        doc, problems = await asyncio.to_thread(_normalize, spec, raw, info.pdf_sha256)
        await asyncio.to_thread(_render_assets, doc, info.pdf, doc_dir / "assets")
        await progress(0.95, "写入文献库")
        migrated, stale = await asyncio.to_thread(self._store, info, spec, raw, doc)
        out = self.get(info.doc_id)
        self._bus.publish("document", out.model_dump(mode="json"))
        if problems:
            log.info("%s: %d IR problems from %s", info.doc_id, len(problems), spec.name)
        return ParseOutcome(status, len(doc.blocks), migrated, stale, len(problems))

    def _load(self, doc_id: str) -> _DocInfo:
        with self._sessions() as s:
            row = s.get(DocumentRow, doc_id)
            if row is None:
                raise LookupError(f"文档 {doc_id} 不存在")
            info = (row.pdf_sha256, row.parse_status, row.parser_engine, row.normalizer_version)
        pdf = self.pdf_path(doc_id)
        if pdf is None:
            raise FileNotFoundError(f"找不到文档 {doc_id} 的 PDF 文件")
        return _DocInfo(doc_id, *info, pdf=pdf)

    def _set_status(self, doc_id: str, status: str) -> None:
        with self._sessions.begin() as s:
            s.execute(
                update(DocumentRow).where(DocumentRow.doc_id == doc_id).values(parse_status=status)
            )
        out = self.get(doc_id)
        if out:
            self._bus.publish("document", out.model_dump(mode="json"))

    def _store(
        self, info: _DocInfo, spec: EngineSpec, raw: RawLayout, doc: Document
    ) -> tuple[int, int]:
        """原子写 ir.json，替换 blocks，迁移译文的块 ID。返回 (迁移数, 失效数)。"""
        ir_path = self.ir_path(info.doc_id)
        tmp = ir_path.with_suffix(".json.tmp")
        tmp.write_text(doc.model_dump_json(exclude_none=True), encoding="utf-8")

        with self._sessions.begin() as s:
            old = [
                _ref_from_row(r)
                for r in s.scalars(select(BlockRow).where(BlockRow.doc_id == info.doc_id))
            ]
            mapping = map_blocks(old, [_ref_from_block(b) for b in doc.blocks]) if old else {}
            migrated, stale = _migrate_translations(s, info.doc_id, mapping) if old else (0, 0)

            s.execute(delete(BlockRow).where(BlockRow.doc_id == info.doc_id))
            s.add_all(
                BlockRow(
                    doc_id=info.doc_id,
                    block_id=b.id,
                    ord=b.order,
                    type=b.type.value,
                    section_id=b.section_id,
                    text=b.text,
                    inlines=[il.model_dump(mode="json", exclude_none=True) for il in b.inlines],
                    latex=b.latex,
                    html=b.html,
                    label=b.label,
                    anchors=[a.model_dump(mode="json") for a in b.anchors],
                    content_hash=b.content_hash,
                )
                for b in doc.blocks
            )
            row = s.get(DocumentRow, info.doc_id)
            row.page_count = doc.source.page_count
            row.ir_path = ir_path.relative_to(self._paths.root).as_posix()
            row.ir_schema_version = IR_SCHEMA_VERSION
            row.parser_engine = spec.name
            row.parser_version = raw.engine_version
            row.normalizer_version = spec.normalizer.version
            row.language = doc.meta.language
            row.parse_status = "ready"
            _backfill_titles(s, info.doc_id, doc.meta.title)
            # 文件替换放在事务里的最后一步：前面任何一步失败都会回滚，旧 ir.json 保持不变
            tmp.replace(ir_path)
        return migrated, stale


def _normalize(spec: EngineSpec, raw: RawLayout, pdf_sha256: str) -> tuple[Document, list[str]]:
    result: Any = spec.normalizer.normalize(raw, pdf_sha256)
    return result if isinstance(result, tuple) else (result, [])


def _render_assets(doc: Document, pdf: Path, assets_dir: Path) -> None:
    """按 bbox 从 PDF 页面截取图 / 表的图片（与引擎无关，快速模式也能显示图）。"""
    import pymupdf

    if assets_dir.exists():
        shutil.rmtree(assets_dir)
    assets_dir.mkdir(parents=True)
    with pymupdf.open(pdf) as pdf_doc:
        for asset in doc.assets:
            if asset.page is None or asset.bbox is None or asset.page >= pdf_doc.page_count:
                continue
            rect = pymupdf.Rect(asset.bbox)
            if rect.is_empty:
                continue
            pix = pdf_doc[asset.page].get_pixmap(clip=rect, dpi=ASSET_DPI)
            pix.save(assets_dir / Path(asset.path).name)
            asset.width_px, asset.height_px = pix.width, pix.height


def _ref_from_row(r: BlockRow) -> BlockRef:
    a = r.anchors[0] if r.anchors else None
    return BlockRef(
        r.block_id,
        r.content_hash,
        r.text,
        a["page"] if a else None,
        tuple(a["bbox"]) if a else None,
    )


def _ref_from_block(b) -> BlockRef:
    a = b.anchors[0] if b.anchors else None
    return BlockRef(b.id, b.content_hash, b.text, a.page if a else None, a.bbox if a else None)


def _migrate_translations(s, doc_id: str, mapping: dict[str, str]) -> tuple[int, int]:
    rows = s.scalars(
        select(TranslationRow).where(
            TranslationRow.doc_id == doc_id, TranslationRow.status != "stale"
        )
    ).all()
    # 新旧 ID 都是 b_0000 起的序号，直接改可能撞上唯一约束：先改成临时 ID，再改回。
    # 失效的译文不再对应任何块，block_id 改成 stale:<行号>:<旧 ID>，免得占住新块的 ID。
    migrated = stale = 0
    for t in rows:
        if t.block_id in mapping:
            t.block_id = "~" + mapping[t.block_id]
            migrated += 1
        else:
            t.block_id = f"stale:{t.id}:{t.block_id}"
            t.status = "stale"
            t.is_active = False
            stale += 1
    s.flush()
    for t in rows:
        t.block_id = t.block_id.removeprefix("~")
    s.flush()
    return migrated, stale


def _backfill_titles(s, doc_id: str, title: str | None) -> None:
    """手动导入、标题取自文件名的条目，用 IR 识别出的标题替换。"""
    if not title:
        return
    items = s.scalars(
        select(ItemRow)
        .join(AttachmentRow, AttachmentRow.item_id == ItemRow.id)
        .where(AttachmentRow.doc_id == doc_id, ItemRow.zotero_key.is_(None))
    ).all()
    for item in items:
        if item.extra.get("title_source") == "filename":
            item.title = title
            item.extra = item.extra | {"title_source": "ir"}
