"""知识图谱：每篇论文一张图（实体不跨文档合并）。见 docs/m3/kg.md。

- 抽取（任务 kg_extract）按章节组调用模型，每条关系都带出处块（domain/kg/extract.py 校验）；
- 各组的实体在文档内按类型 + 别名合并，再只留下重要的（domain/kg/extract.prune）；
- 重新抽取整体替换该文档的图；
- 重新解析时出处块按块映射迁移（migrate_kg，与译文、总结、问答同一事务）。
"""

import asyncio
import logging
from collections import defaultdict
from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy import delete, select, update

from freeread.config import DataPaths
from freeread.domain.kg.extract import DocGraph, entity_scores, merge_groups, parse_group, prune
from freeread.domain.kg.normalize import name_norm
from freeread.domain.summary.grouping import group_blocks
from freeread.domain.summary.parse_json import extract_json
from freeread.infra.db.engine import SessionFactory
from freeread.infra.db.models import DocumentRow, KGEntityRow, KGMentionRow, KGRelationRow
from freeread.infra.jobs.events import EventBus
from freeread.infra.jobs.queue import JobOut, JobQueue, JobStatus
from freeread.infra.jobs.worker import JobContext
from freeread.infra.llm.default_gateway import DefaultGateway
from freeread.infra.llm.errors import LLMError, ProviderError
from freeread.infra.llm.gateway import Message, TaskKind
from freeread.infra.llm.prompts import Prompt, PromptRegistry
from freeread.infra.search.chunker import approx_tokens
from freeread.services.doc_blocks import DocumentNotReady, load_doc
from freeread.services.llm_preflight import PreflightError, check_provider
from freeread.services.settings import SettingsService

log = logging.getLogger(__name__)

PROMPT_ID = "kg_extract"
GROUP_TARGET = 2500  # 比总结的 Map 小：输出是逐条的实体 / 关系，组大了容易漏
GROUP_MAX = 5000
# 一篇文档内同时调用的组数；None 跟随图谱抽取所用服务的并发设置（评测脚本可覆盖）
CONCURRENCY: int | None = None
FATAL_STATUS = {401, 402, 403}

T = TypeVar("T")


class EntityOut(BaseModel):
    id: str
    type: str
    name: str
    description: str
    aliases: list[str]  # 不含 name
    block_ids: list[str]  # 出现的块，按阅读顺序
    score: int  # 2 × 关系数 + 提及块数（云图节点大小）


class RelationOut(BaseModel):
    id: str
    type: str
    src_id: str
    src_name: str
    dst_id: str
    dst_name: str
    attrs: dict[str, Any]
    block_id: str
    evidence: str
    confidence: float
    status: str  # ok | stale


class DocGraphOut(BaseModel):
    doc_id: str
    kg_status: str
    entities: list[EntityOut]
    relations: list[RelationOut]


def migrate_kg(s, doc_id: str, mapping: dict[str, str]) -> int:
    """重新解析后改写提及和关系的出处块（与译文、总结迁移同一事务，见 ParseService._store）。

    映射不上的提及删除，关系标 stale（保留，界面显示"出处已失效"）。返回标 stale 的关系数。
    """
    for m in s.scalars(select(KGMentionRow).where(KGMentionRow.doc_id == doc_id)):
        new = mapping.get(m.block_id)
        if new is None:
            s.delete(m)
        else:
            m.block_id = new
    stale = 0
    for r in s.scalars(select(KGRelationRow).where(KGRelationRow.doc_id == doc_id)):
        new = mapping.get(r.source_block_id)
        if new is None:
            if r.status == "ok":
                r.status = "stale"
                stale += 1
        else:
            r.source_block_id = new
    return stale


class KGService:
    def __init__(
        self,
        sessions: SessionFactory,
        paths: DataPaths,
        jobs: JobQueue,
        bus: EventBus,
        settings: SettingsService,
        gateway: DefaultGateway,
        prompts: PromptRegistry,
    ) -> None:
        self._sessions = sessions
        self._paths = paths
        self._jobs = jobs
        self._bus = bus
        self._settings = settings
        self._gateway = gateway
        self._prompts = prompts
        # 透传给 provider 的额外请求参数（如关闭推理模型的思考）；会进入缓存键。评测脚本用。
        self.llm_opts: dict[str, Any] = {}

    # ------------------------------------------------------------ 排队

    def request_extract(self, doc_id: str) -> JobOut:
        """检查文档与模型可用（不可用时抛 LookupError / DocumentNotReady / PreflightError），排队抽取任务。"""
        load_doc(self._sessions, self._paths, doc_id)
        check_provider(self._gateway, self._settings, TaskKind.KG_EXTRACT)
        existing = self._jobs.find_active("kg_extract", doc_id=doc_id)
        return existing or self._jobs.enqueue("kg_extract", {"doc_id": doc_id})

    def enqueue_auto(self, doc_id: str) -> JobOut | None:
        """嵌入完成后调用：设置里开了自动抽取、模型可用且已确认发送时才排队，否则什么都不做。"""
        if not self._settings.get().kg.auto:
            return None
        try:
            check_provider(self._gateway, self._settings, TaskKind.KG_EXTRACT)
        except PreflightError:
            return None
        existing = self._jobs.find_active("kg_extract", (JobStatus.QUEUED,), doc_id=doc_id)
        return existing or self._jobs.enqueue("kg_extract", {"doc_id": doc_id})

    # ------------------------------------------------------------ 抽取任务

    async def run_extract_job(self, ctx: JobContext) -> None:
        doc_id = ctx.job.payload["doc_id"]
        provider_id, model = check_provider(self._gateway, self._settings, TaskKind.KG_EXTRACT)
        prompt = self._prompts.get(PROMPT_ID)
        extractor = f"{provider_id}/{model}+{prompt.ref}"
        had_graph = await asyncio.to_thread(self._status, doc_id) == "ready"
        await asyncio.to_thread(self._set_status, doc_id, "extracting")
        try:
            graph = prune(await self._extract(doc_id, prompt, ctx))
            await asyncio.to_thread(self._store, doc_id, graph, extractor)
        except BaseException:
            await asyncio.to_thread(self._set_status, doc_id, "ready" if had_graph else "failed")
            raise
        msg = f"{len(graph.entities)} 个实体、{len(graph.relations)} 条关系"
        extra = []
        if graph.stats["pruned"]:
            extra.append(f"略去 {graph.stats['pruned']} 个次要实体")
        if graph.stats["unverified_values"]:
            extra.append(f"丢弃 {graph.stats['unverified_values']} 条原文里找不到的数值")
        if graph.stats["failed_groups"]:
            extra.append(f"{graph.stats['failed_groups']} 组失败")
        await ctx.report(1.0, msg + (f"（{'，'.join(extra)}）" if extra else ""))

    async def _extract(self, doc_id: str, prompt: Prompt, ctx: JobContext) -> DocGraph:
        from freeread.services.summary import source_blocks  # 避免循环导入

        try:
            doc = await asyncio.to_thread(load_doc, self._sessions, self._paths, doc_id)
        except DocumentNotReady as e:
            raise RuntimeError(str(e)) from e
        blocks = source_blocks(doc)
        texts = {b.id: b.text for b in blocks if b.text and b.type != "heading"}
        groups = group_blocks(
            blocks, doc.sections, approx_tokens, target=GROUP_TARGET, max_tokens=GROUP_MAX
        )
        if not groups:
            raise RuntimeError("文档里没有可抽取图谱的正文")
        sem = asyncio.Semaphore(CONCURRENCY or self._gateway.concurrency(TaskKind.KG_EXTRACT))
        done = 0
        errors: list[Exception] = []
        # 401 / 402 / 403（密钥无效、余额不足、无权限）后面的组也一定失败：不再调用，整个任务失败
        fatal: list[ProviderError] = []
        await ctx.report(0.02, f"抽取图谱：0 / {len(groups)} 组")

        async def one(group):
            nonlocal done
            messages = prompt.render(
                title=doc.title, group_title=group.title, content=group.content
            )
            data = None
            try:
                async with sem:
                    if not fatal:
                        data = await self._complete_json(
                            doc_id, prompt, messages, lambda t: extract_json(t, "entities")
                        )
            except (LLMError, ValueError) as e:
                log.warning("kg %s / %s failed: %s", doc_id, group.title, e)
                errors.append(e)
                if isinstance(e, ProviderError) and e.status_code in FATAL_STATUS:
                    fatal.append(e)
            done += 1
            await ctx.report(
                0.02 + 0.85 * done / len(groups), f"抽取图谱：{done} / {len(groups)} 组"
            )
            if data is None:
                return None
            return parse_group(data, {b: texts[b] for b in group.block_ids if b in texts})

        results = await asyncio.gather(*(one(g) for g in groups))
        if fatal:
            raise RuntimeError(f"调用模型失败：{fatal[0]}")
        ok = [r for r in results if r is not None]
        if not ok:
            reason = f"：{errors[0]}" if errors else ""
            raise RuntimeError(f"{len(groups)} 组都没有得到可用的抽取结果{reason}")
        graph = merge_groups(ok)
        graph.stats["failed_groups"] = len(results) - len(ok)
        return graph

    async def _complete_json(
        self, doc_id: str, prompt: Prompt, messages: list[Message], parse: Callable[[str], T]
    ) -> T:
        """parse 抛 ValueError 时不走缓存重试一次（缓存里是那条坏回复）。"""
        for attempt in range(2):
            result = await self._gateway.complete(
                TaskKind.KG_EXTRACT,
                messages,
                prompt_id=prompt.ref,
                doc_id=doc_id,
                use_cache=attempt == 0,
                **self.llm_opts,
            )
            try:
                return parse(result.text)
            except ValueError:
                if attempt == 1:
                    raise
                log.info("kg %s: invalid reply from %s, retrying", doc_id, prompt.ref)
        raise AssertionError("unreachable")

    # ------------------------------------------------------------ 写入

    def _store(self, doc_id: str, graph: DocGraph, extractor: str) -> None:
        """单事务替换该文档的整张图。"""
        scores = entity_scores(graph)
        with self._sessions.begin() as s:
            s.execute(delete(KGRelationRow).where(KGRelationRow.doc_id == doc_id))
            s.execute(delete(KGMentionRow).where(KGMentionRow.doc_id == doc_id))
            s.execute(delete(KGEntityRow).where(KGEntityRow.doc_id == doc_id))
            ids: list[str] = []
            for ent, score in zip(graph.entities, scores, strict=True):
                row = KGEntityRow(
                    doc_id=doc_id,
                    type=ent.type.value,
                    name=ent.name,
                    name_norm=name_norm(ent.name),
                    aliases=ent.aliases,
                    description=ent.description,
                    score=score,
                )
                s.add(row)
                s.flush()
                ids.append(row.id)
                for bid, surface in ent.mentions.items():
                    s.add(
                        KGMentionRow(entity_id=row.id, doc_id=doc_id, block_id=bid, surface=surface)
                    )
            for r in graph.relations:
                s.add(
                    KGRelationRow(
                        doc_id=doc_id,
                        src_id=ids[r.src],
                        dst_id=ids[r.dst],
                        type=r.type.value,
                        attrs=r.attrs,
                        source_block_id=r.block_id,
                        evidence=r.evidence,
                        confidence=round(r.confidence, 3),
                        extractor=extractor,
                    )
                )
            s.execute(
                update(DocumentRow).where(DocumentRow.doc_id == doc_id).values(kg_status="ready")
            )
        self._publish(doc_id)

    def _status(self, doc_id: str) -> str | None:
        with self._sessions() as s:
            return s.scalar(select(DocumentRow.kg_status).where(DocumentRow.doc_id == doc_id))

    def _set_status(self, doc_id: str, status: str) -> None:
        with self._sessions.begin() as s:
            s.execute(
                update(DocumentRow).where(DocumentRow.doc_id == doc_id).values(kg_status=status)
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

    # ------------------------------------------------------------ 查询

    def doc_graph(self, doc_id: str) -> DocGraphOut:
        with self._sessions() as s:
            doc = s.get(DocumentRow, doc_id)
            if doc is None:
                raise LookupError(f"文档 {doc_id} 不存在")
            blocks: dict[str, set[str]] = defaultdict(set)
            for eid, bid in s.execute(
                select(KGMentionRow.entity_id, KGMentionRow.block_id).where(
                    KGMentionRow.doc_id == doc_id
                )
            ):
                blocks[eid].add(bid)
            rows = s.scalars(select(KGEntityRow).where(KGEntityRow.doc_id == doc_id)).all()
            entities = [
                EntityOut(
                    id=r.id,
                    type=r.type,
                    name=r.name,
                    description=r.description,
                    aliases=[a for a in r.aliases or [] if a != r.name],
                    block_ids=sorted(blocks[r.id]),
                    score=r.score,
                )
                for r in rows
            ]
            names = {e.id: e.name for e in entities}
            relations = [
                RelationOut(
                    id=r.id,
                    type=r.type,
                    src_id=r.src_id,
                    src_name=names.get(r.src_id, ""),
                    dst_id=r.dst_id,
                    dst_name=names.get(r.dst_id, ""),
                    attrs=r.attrs or {},
                    block_id=r.source_block_id,
                    evidence=r.evidence,
                    confidence=r.confidence,
                    status=r.status,
                )
                for r in s.scalars(select(KGRelationRow).where(KGRelationRow.doc_id == doc_id))
            ]
            return DocGraphOut(
                doc_id=doc_id,
                kg_status=doc.kg_status,
                entities=sorted(entities, key=lambda e: (-e.score, e.name.casefold())),
                relations=sorted(relations, key=lambda r: (r.block_id, r.type)),
            )
