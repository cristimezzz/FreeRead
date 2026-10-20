"""知识图谱：抽取任务、跨文档消歧、用户合并 / 拆分、查询。见 docs/m3/kg.md。

- 抽取（任务 kg_extract）按章节组调用模型，每条关系都带出处块（domain/kg/extract.py 校验）；
- 实体全库共享：别名精确命中直接合并，否则按嵌入相似度合并，模糊区间交给模型判定
  （domain/kg/resolve.py）；
- 重新抽取只替换该文档的提及和关系：用户删除的关系（rejected）不会加回，用户合并 / 拆分过的
  实体靠别名归属和 kg_distinct 保持不变；
- 重新解析时出处块按块映射迁移（migrate_kg，与译文、总结、问答同一事务）。
"""

import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterable
from typing import Any, TypeVar

import numpy as np
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select, union, update

from freeread.config import DataPaths
from freeread.domain.kg.extract import DocGraph, merge_groups, parse_group
from freeread.domain.kg.normalize import clean_name, name_norm
from freeread.domain.kg.resolve import (
    NO_CROSS_DOC,
    Decision,
    decide,
    embed_text,
    from_blob,
    to_blob,
    top_similar,
)
from freeread.domain.kg.schema import EntityType
from freeread.domain.summary.grouping import group_blocks
from freeread.domain.summary.parse_json import extract_json
from freeread.infra.db.engine import SessionFactory
from freeread.infra.db.models import (
    AttachmentRow,
    DocumentRow,
    ItemRow,
    KGAliasRow,
    KGDistinctRow,
    KGEntityRow,
    KGMentionRow,
    KGMergeSuggestionRow,
    KGRelationRow,
)
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
RESOLVE_PROMPT_ID = "kg_resolve"
GROUP_TARGET = 2500  # 比总结的 Map 小：输出是逐条的实体 / 关系，组大了容易漏
GROUP_MAX = 5000
CONCURRENCY = 2  # 一篇文档内同时调用的组数
RESOLVE_BATCH = 40  # 一次判定多少对
BACKFILL_LIMIT = 500  # 每次抽取最多给多少个旧实体补算向量
LIST_LIMIT = 200
FATAL_STATUS = {401, 402, 403}

T = TypeVar("T")
# 文本 → (嵌入模型 key, 向量)；嵌入不可用时返回 None
EmbedFn = Callable[[list[str]], Awaitable[tuple[str, list[list[float]]] | None]]


class EntityOut(BaseModel):
    id: str
    type: str
    name: str
    description: str
    origin: str  # auto | user
    aliases: list[str]
    block_ids: list[str] = []  # 在当前文档里出现的块（doc_graph 才有）
    doc_count: int = 0  # 出现在几篇文档里


class RelationOut(BaseModel):
    id: str
    type: str
    src_id: str
    src_name: str
    src_type: str
    dst_id: str
    dst_name: str
    dst_type: str
    attrs: dict[str, Any]
    doc_id: str
    doc_title: str = ""
    block_id: str
    evidence: str
    confidence: float
    status: str  # ok | stale


class MentionOut(BaseModel):
    doc_id: str
    doc_title: str
    block_id: str
    surface: str


class SuggestionOut(BaseModel):
    """可能重复：确认后把 entity 并入 candidate。"""

    id: str
    score: float  # 嵌入余弦相似度
    entity: EntityOut
    candidate: EntityOut


class DocGraphOut(BaseModel):
    doc_id: str
    kg_status: str
    entities: list[EntityOut]
    relations: list[RelationOut]
    suggestions: list[SuggestionOut] = []  # 涉及本篇实体的合并建议


class EntityDetailOut(BaseModel):
    entity: EntityOut
    mentions: list[MentionOut]
    relations: list[RelationOut]


class SubgraphOut(BaseModel):
    entities: list[EntityOut]
    relations: list[RelationOut]


class EntityPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    type: EntityType | None = None
    description: str | None = Field(default=None, max_length=300)


class MergeIn(BaseModel):
    source_ids: list[str] = Field(min_length=1)


class SplitIn(BaseModel):
    aliases: list[str] = Field(min_length=1)


class KGEditError(ValueError):
    """合并 / 拆分的参数不合法（API 返回 400）。"""


def _pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


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
        embed_texts: EmbedFn | None = None,
    ) -> None:
        self._sessions = sessions
        self._paths = paths
        self._jobs = jobs
        self._bus = bus
        self._settings = settings
        self._gateway = gateway
        self._prompts = prompts
        self.embed_texts = embed_texts
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
            graph = await self._extract(doc_id, prompt, ctx)
            await ctx.report(0.9, "合并实体")
            matches, vectors, merged, suggested = await self._resolve(doc_id, graph)
            n_rel, n_suggested = await asyncio.to_thread(
                self._store, doc_id, graph, matches, vectors, extractor, suggested
            )
        except BaseException:
            await asyncio.to_thread(self._set_status, doc_id, "ready" if had_graph else "failed")
            raise
        msg = f"{len(graph.entities)} 个实体、{n_rel} 条关系"
        extra = []
        if merged:
            extra.append(f"与已有实体合并 {merged} 个")
        if n_suggested:
            extra.append(f"{n_suggested} 个可能重复待确认")
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
        sem = asyncio.Semaphore(CONCURRENCY)
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

    # ------------------------------------------------------------ 消歧

    async def _resolve(
        self, doc_id: str, graph: DocGraph
    ) -> tuple[
        dict[int, str], dict[int, tuple[str, list[float]]], int, dict[int, tuple[str, float]]
    ]:
        """返回 (精确匹配：本篇实体下标 → 已有实体 id, 新实体的向量, 合并到已有实体的个数,
        合并建议：本篇实体下标 → (已有实体 id, 相似度))。

        只有别名精确相同才自动合并；嵌入候选经模型判定为同一个的只作为建议，等用户确认。
        """
        matches = await asyncio.to_thread(self._exact_matches, graph)
        vectors: dict[int, tuple[str, list[float]]] = {}
        suggested: dict[int, tuple[str, float]] = {}
        pending = [
            i
            for i, e in enumerate(graph.entities)
            if i not in matches and e.type not in NO_CROSS_DOC
        ]
        embedded = None
        if pending and self.embed_texts is not None:
            embedded = await self.embed_texts(
                [
                    embed_text(e.type, e.name, e.description)
                    for e in (graph.entities[i] for i in pending)
                ]
            )
        if embedded is not None:
            model_key, vecs = embedded
            vectors = {i: (model_key, v) for i, v in zip(pending, vecs, strict=True)}
            types = {graph.entities[i].type.value for i in pending}
            await self._backfill_embeddings(types, model_key)
            candidates = await asyncio.to_thread(self._candidate_matrix, types, model_key)
            pairs: list[tuple[int, str]] = []
            sims: dict[int, float] = {}
            for i in pending:
                ent = graph.entities[i]
                ids, names, matrix = candidates.get(ent.type.value, ([], [], np.empty((0, 0))))
                query = np.asarray(vectors[i][1], dtype="<f4")
                # 最相似的几个里第一个值得判定的（跳过数字不同的版本 / 变体）
                for row, sim in top_similar(query, matrix):
                    if decide(sim, ent.name, names[row]) is Decision.JUDGE:
                        pairs.append((i, ids[row]))
                        sims[i] = sim
                        break
            if pairs:
                same = await self._judge(doc_id, graph, pairs)
                suggested = {i: (eid, round(sims[i], 4)) for i, eid in same.items()}
        merged = await asyncio.to_thread(self._count_cross_doc, set(matches.values()), doc_id)
        return matches, vectors, merged, suggested

    def _count_cross_doc(self, ids: set[str], doc_id: str) -> int:
        """其中有几个实体也出现在别的文档里（重新抽取时命中本篇旧实体的不算合并）。"""
        if not ids:
            return 0
        with self._sessions() as s:
            return len(
                set(
                    s.scalars(
                        select(KGMentionRow.entity_id).where(
                            KGMentionRow.entity_id.in_(ids), KGMentionRow.doc_id != doc_id
                        )
                    )
                )
            )

    def _exact_matches(self, graph: DocGraph) -> dict[int, str]:
        """别名归一化后精确相同（同类型）的已有实体。名称本身命中优先于其他别名命中。"""
        out: dict[int, str] = {}
        norms = {n for e in graph.entities if e.type not in NO_CROSS_DOC for n in e.norms()}
        if not norms:
            return out
        owners: dict[tuple[str, str], list[str]] = defaultdict(list)
        with self._sessions() as s:
            rows = s.execute(
                select(KGAliasRow.alias_norm, KGEntityRow.type, KGEntityRow.id)
                .join(KGEntityRow, KGEntityRow.id == KGAliasRow.entity_id)
                .where(KGAliasRow.alias_norm.in_(norms))
                .order_by(KGEntityRow.created_at)
            ).all()
        for alias_norm, etype, eid in rows:
            owners[(etype, alias_norm)].append(eid)
        for i, e in enumerate(graph.entities):
            if e.type in NO_CROSS_DOC:
                continue
            hit = next((owners[(e.type, n)][0] for n in e.norms() if owners.get((e.type, n))), None)
            if hit is not None:
                out[i] = hit
        return out

    def _candidate_matrix(
        self, types: Iterable[str], model_key: str
    ) -> dict[str, tuple[list[str], list[str], np.ndarray]]:
        """类型 → (实体 id, 名称, 向量矩阵)；只取同一嵌入模型的向量。"""
        out: dict[str, tuple[list[str], list[str], np.ndarray]] = {}
        with self._sessions() as s:
            for etype in types:
                rows = s.execute(
                    select(KGEntityRow.id, KGEntityRow.name, KGEntityRow.embedding).where(
                        KGEntityRow.type == etype,
                        KGEntityRow.embedding_model == model_key,
                        KGEntityRow.embedding.is_not(None),
                    )
                ).all()
                if rows:
                    out[etype] = (
                        [r[0] for r in rows],
                        [r[1] for r in rows],
                        np.stack([from_blob(r[2]) for r in rows]),
                    )
        return out

    async def _backfill_embeddings(self, types: Iterable[str], model_key: str) -> None:
        """给这些类型里没有向量（用户改名 / 拆分后会清空）或向量来自别的模型的实体补算。"""
        if self.embed_texts is None:
            return
        types = list(types)

        def load() -> list[tuple[str, str]]:
            with self._sessions() as s:
                rows = s.scalars(
                    select(KGEntityRow)
                    .where(
                        KGEntityRow.type.in_(types),
                        or_(
                            KGEntityRow.embedding.is_(None),
                            KGEntityRow.embedding_model != model_key,
                        ),
                    )
                    .limit(BACKFILL_LIMIT)
                ).all()
                return [(r.id, embed_text(r.type, r.name, r.description)) for r in rows]

        todo = await asyncio.to_thread(load)
        if not todo:
            return
        embedded = await self.embed_texts([t for _, t in todo])
        if embedded is None:
            return
        key, vecs = embedded

        def save() -> None:
            with self._sessions.begin() as s:
                for (eid, _), v in zip(todo, vecs, strict=True):
                    s.execute(
                        update(KGEntityRow)
                        .where(KGEntityRow.id == eid)
                        .values(embedding=to_blob(v), embedding_model=key)
                    )

        await asyncio.to_thread(save)

    async def _judge(
        self, doc_id: str, graph: DocGraph, pairs: list[tuple[int, str]]
    ) -> dict[int, str]:
        """嵌入找到的候选实体对交给模型判定；调用或解析失败时一律不合并（保守）。"""
        prompt = self._prompts.get(RESOLVE_PROMPT_ID)
        existing = await asyncio.to_thread(self._entities_by_id, [eid for _, eid in pairs])
        out: dict[int, str] = {}
        for start in range(0, len(pairs), RESOLVE_BATCH):
            batch = pairs[start : start + RESOLVE_BATCH]
            items = []
            for n, (i, eid) in enumerate(batch, 1):
                e, other = graph.entities[i], existing.get(eid)
                if other is None:
                    continue
                items.append(
                    {
                        "id": n,
                        "type": e.type.value,
                        "a_name": e.name,
                        "a_desc": e.description,
                        "b_name": other.name,
                        "b_desc": other.description,
                    }
                )
            if not items:
                continue
            try:
                data = await self._complete_json(
                    doc_id, prompt, prompt.render(pairs=items), lambda t: extract_json(t, "answers")
                )
            except (LLMError, ValueError) as e:
                log.warning("kg resolve %s failed: %s", doc_id, e)
                continue
            for ans in data.get("answers") or []:
                # 只有明确说"同一个"才合并；上下位、相关、不确定都不合并
                if not isinstance(ans, dict) or str(ans.get("relation", "")).lower() != "same":
                    continue
                try:
                    i, eid = batch[int(ans.get("id")) - 1]
                except (TypeError, ValueError, IndexError):
                    continue
                out[i] = eid
        return out

    def _entities_by_id(self, ids: Iterable[str]) -> dict[str, KGEntityRow]:
        with self._sessions() as s:
            rows = s.scalars(select(KGEntityRow).where(KGEntityRow.id.in_(list(ids)))).all()
            for r in rows:
                s.expunge(r)
            return {r.id: r for r in rows}

    # ------------------------------------------------------------ 写入

    def _store(
        self,
        doc_id: str,
        graph: DocGraph,
        matches: dict[int, str],
        vectors: dict[int, tuple[str, list[float]]],
        extractor: str,
        suggested: dict[int, tuple[str, float]] | None = None,
    ) -> tuple[int, int]:
        """单事务替换该文档的提及、关系和合并建议。返回 (写入的关系数, 合并建议数)。"""
        with self._sessions.begin() as s:
            rejected = {
                (r.src_id, r.dst_id, r.type, r.source_block_id)
                for r in s.scalars(
                    select(KGRelationRow).where(
                        KGRelationRow.doc_id == doc_id, KGRelationRow.status == "rejected"
                    )
                )
            }
            s.execute(delete(KGMentionRow).where(KGMentionRow.doc_id == doc_id))
            s.execute(delete(KGMergeSuggestionRow).where(KGMergeSuggestionRow.doc_id == doc_id))
            s.execute(
                delete(KGRelationRow).where(
                    KGRelationRow.doc_id == doc_id, KGRelationRow.status != "rejected"
                )
            )
            distinct = {
                _pair(a, b) for a, b in s.execute(select(KGDistinctRow.a_id, KGDistinctRow.b_id))
            }
            norms = {n for e in graph.entities for n in e.norms()} | {
                name_norm(sf) for e in graph.entities for sf in e.mentions.values()
            }
            owners: dict[tuple[str, str], str] = {}
            for alias_norm, etype, eid in s.execute(
                select(KGAliasRow.alias_norm, KGEntityRow.type, KGEntityRow.id)
                .join(KGEntityRow, KGEntityRow.id == KGAliasRow.entity_id)
                .where(KGAliasRow.alias_norm.in_(norms))
            ):
                owners.setdefault((etype, alias_norm), eid)

            def owner_for(eid: str, etype: str, surface: str) -> str:
                """用户拆分出去的写法归到拆出来的实体（kg_distinct 里的那一个）。"""
                other = owners.get((etype, name_norm(surface)))
                if other and other != eid and _pair(eid, other) in distinct:
                    return other
                return eid

            ids: list[str] = []
            for i, ent in enumerate(graph.entities):
                row = s.get(KGEntityRow, matches[i]) if i in matches else None
                if row is None:
                    model_key, vec = vectors.get(i, (None, None))
                    row = KGEntityRow(
                        type=ent.type.value,
                        name=ent.name,
                        name_norm=name_norm(ent.name),
                        description=ent.description,
                        origin="auto",
                        embedding=to_blob(vec) if vec is not None else None,
                        embedding_model=model_key,
                    )
                    s.add(row)
                    s.flush()
                elif not row.description and ent.description:
                    row.description = ent.description
                have = set(
                    s.scalars(select(KGAliasRow.alias_norm).where(KGAliasRow.entity_id == row.id))
                )
                for alias in ent.aliases:
                    n = name_norm(alias)
                    if n in have or owner_for(row.id, row.type, alias) != row.id:
                        continue
                    s.add(KGAliasRow(entity_id=row.id, alias_norm=n, alias=alias, origin="auto"))
                    have.add(n)
                    owners.setdefault((row.type, n), row.id)
                for bid, surface in ent.mentions.items():
                    s.add(
                        KGMentionRow(
                            entity_id=owner_for(row.id, row.type, surface),
                            doc_id=doc_id,
                            block_id=bid,
                            surface=surface,
                            surface_norm=name_norm(surface),
                            extractor=extractor,
                        )
                    )
                ids.append(row.id)

            written = 0
            for r in graph.relations:
                src_e, dst_e = graph.entities[r.src], graph.entities[r.dst]
                src_surface = src_e.mentions.get(r.block_id, src_e.name)
                dst_surface = dst_e.mentions.get(r.block_id, dst_e.name)
                src = owner_for(ids[r.src], src_e.type.value, src_surface)
                dst = owner_for(ids[r.dst], dst_e.type.value, dst_surface)
                if src == dst or (src, dst, r.type.value, r.block_id) in rejected:
                    continue
                s.add(
                    KGRelationRow(
                        src_id=src,
                        dst_id=dst,
                        type=r.type.value,
                        attrs=r.attrs,
                        doc_id=doc_id,
                        source_block_id=r.block_id,
                        src_surface=src_surface,
                        dst_surface=dst_surface,
                        evidence=r.evidence,
                        confidence=round(r.confidence, 3),
                        extractor=extractor,
                    )
                )
                written += 1
            for i, (candidate, score) in (suggested or {}).items():
                eid = ids[i]
                if eid == candidate or _pair(eid, candidate) in distinct:
                    continue
                exists = s.scalar(
                    select(KGMergeSuggestionRow.id).where(
                        KGMergeSuggestionRow.entity_id == eid,
                        KGMergeSuggestionRow.candidate_id == candidate,
                    )
                )
                if exists is None:
                    s.add(
                        KGMergeSuggestionRow(
                            entity_id=eid, candidate_id=candidate, doc_id=doc_id, score=score
                        )
                    )
            s.flush()
            _collect_garbage(s)  # 候选是本篇旧的自动实体时会被回收，建议随之级联删除
            n_suggested = (
                s.scalar(
                    select(func.count())
                    .select_from(KGMergeSuggestionRow)
                    .where(KGMergeSuggestionRow.doc_id == doc_id)
                )
                or 0
            )
            s.execute(
                update(DocumentRow).where(DocumentRow.doc_id == doc_id).values(kg_status="ready")
            )
        self._publish(doc_id)
        return written, n_suggested

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

    # ------------------------------------------------------------ 用户编辑

    def update_entity(self, entity_id: str, patch: EntityPatch) -> EntityOut:
        with self._sessions.begin() as s:
            row = self._get(s, entity_id)
            if patch.name is not None and clean_name(patch.name):
                name = clean_name(patch.name)
                row.name, row.name_norm = name, name_norm(name)
                if s.get(KGAliasRow, (row.id, row.name_norm)) is None:
                    s.add(
                        KGAliasRow(
                            entity_id=row.id, alias_norm=row.name_norm, alias=name, origin="user"
                        )
                    )
            if patch.type is not None:
                row.type = patch.type.value
            if patch.description is not None:
                row.description = patch.description.strip()
            row.origin = "user"
            row.embedding = row.embedding_model = None  # 下次抽取时补算
            s.flush()
            return self._entity_out(s, row)

    def merge(self, target_id: str, source_ids: list[str]) -> EntityOut:
        """把 source 实体并入 target：别名、提及、关系端点都转给 target，source 删除。"""
        sources = [i for i in dict.fromkeys(source_ids) if i != target_id]
        if not sources:
            raise KGEditError("没有要合并的实体")
        with self._sessions.begin() as s:
            target = self._get(s, target_id)
            have = set(
                s.scalars(select(KGAliasRow.alias_norm).where(KGAliasRow.entity_id == target_id))
            )
            for sid in sources:
                src = self._get(s, sid)
                for alias in s.scalars(select(KGAliasRow).where(KGAliasRow.entity_id == sid)):
                    if alias.alias_norm not in have:
                        s.add(
                            KGAliasRow(
                                entity_id=target_id,
                                alias_norm=alias.alias_norm,
                                alias=alias.alias,
                                origin="user",
                            )
                        )
                        have.add(alias.alias_norm)
                s.flush()
                s.execute(
                    update(KGMentionRow)
                    .where(KGMentionRow.entity_id == sid)
                    .values(entity_id=target_id)
                )
                s.execute(
                    update(KGRelationRow)
                    .where(KGRelationRow.src_id == sid)
                    .values(src_id=target_id)
                )
                s.execute(
                    update(KGRelationRow)
                    .where(KGRelationRow.dst_id == sid)
                    .values(dst_id=target_id)
                )
                if not target.description and src.description:
                    target.description = src.description
                s.delete(src)
            s.execute(delete(KGRelationRow).where(KGRelationRow.src_id == KGRelationRow.dst_id))
            s.execute(
                update(KGAliasRow).where(KGAliasRow.entity_id == target_id).values(origin="user")
            )
            target.origin = "user"
            s.flush()
            return self._entity_out(s, target)

    def split(self, entity_id: str, aliases: list[str]) -> EntityOut:
        """把选中的别名（及以这些写法出现的提及、关系端点）拆成一个新实体。返回新实体。"""
        norms = {name_norm(a) for a in aliases} - {""}
        with self._sessions.begin() as s:
            row = self._get(s, entity_id)
            alias_rows = list(
                s.scalars(select(KGAliasRow).where(KGAliasRow.entity_id == entity_id))
            )
            moving = [a for a in alias_rows if a.alias_norm in norms]
            staying = [a for a in alias_rows if a.alias_norm not in norms]
            if not moving:
                raise KGEditError("选中的别名不属于这个实体")
            if not staying:
                raise KGEditError("至少要留一个别名给原实体")
            new = KGEntityRow(
                type=row.type,
                name=moving[0].alias,
                name_norm=moving[0].alias_norm,
                description="",
                origin="user",
            )
            s.add(new)
            s.flush()
            for a in moving:
                s.add(
                    KGAliasRow(
                        entity_id=new.id, alias_norm=a.alias_norm, alias=a.alias, origin="user"
                    )
                )
                s.delete(a)
            s.execute(
                update(KGMentionRow)
                .where(KGMentionRow.entity_id == entity_id, KGMentionRow.surface_norm.in_(norms))
                .values(entity_id=new.id)
            )
            for r in s.scalars(
                select(KGRelationRow).where(
                    or_(KGRelationRow.src_id == entity_id, KGRelationRow.dst_id == entity_id)
                )
            ):
                if r.src_id == entity_id and name_norm(r.src_surface) in norms:
                    r.src_id = new.id
                if r.dst_id == entity_id and name_norm(r.dst_surface) in norms:
                    r.dst_id = new.id
            a_id, b_id = _pair(entity_id, new.id)
            s.add(KGDistinctRow(a_id=a_id, b_id=b_id))
            if row.name_norm in norms:
                row.name, row.name_norm = staying[0].alias, staying[0].alias_norm
            for a in staying:
                a.origin = "user"
            row.origin = "user"
            row.embedding = row.embedding_model = None
            s.flush()
            return self._entity_out(s, new)

    def accept_suggestion(self, suggestion_id: str) -> EntityOut:
        """确认合并建议：把建议里的实体并入候选实体。"""
        with self._sessions() as s:
            row = s.get(KGMergeSuggestionRow, suggestion_id)
            if row is None:
                raise LookupError(f"合并建议 {suggestion_id} 不存在")
            target, source = row.candidate_id, row.entity_id
        return self.merge(target, [source])  # 源实体删除，建议随之级联删除

    def dismiss_suggestion(self, suggestion_id: str) -> None:
        """否决合并建议：记为不是同一个，以后不再建议。"""
        with self._sessions.begin() as s:
            row = s.get(KGMergeSuggestionRow, suggestion_id)
            if row is None:
                raise LookupError(f"合并建议 {suggestion_id} 不存在")
            a_id, b_id = _pair(row.entity_id, row.candidate_id)
            if s.get(KGDistinctRow, (a_id, b_id)) is None:
                s.add(KGDistinctRow(a_id=a_id, b_id=b_id))
            s.delete(row)

    def reject_relation(self, relation_id: str) -> bool:
        with self._sessions.begin() as s:
            n = s.execute(
                update(KGRelationRow)
                .where(KGRelationRow.id == relation_id)
                .values(status="rejected")
            ).rowcount
        return n > 0

    @staticmethod
    def _get(s, entity_id: str) -> KGEntityRow:
        row = s.get(KGEntityRow, entity_id)
        if row is None:
            raise LookupError(f"实体 {entity_id} 不存在")
        return row

    # ------------------------------------------------------------ 查询

    def doc_graph(self, doc_id: str) -> DocGraphOut:
        with self._sessions() as s:
            doc = s.get(DocumentRow, doc_id)
            if doc is None:
                raise LookupError(f"文档 {doc_id} 不存在")
            blocks: dict[str, list[str]] = defaultdict(list)
            for eid, bid in s.execute(
                select(KGMentionRow.entity_id, KGMentionRow.block_id).where(
                    KGMentionRow.doc_id == doc_id
                )
            ):
                if bid not in blocks[eid]:
                    blocks[eid].append(bid)
            rel_rows = list(
                s.scalars(
                    select(KGRelationRow).where(
                        KGRelationRow.doc_id == doc_id, KGRelationRow.status != "rejected"
                    )
                )
            )
            ids = set(blocks) | {r.src_id for r in rel_rows} | {r.dst_id for r in rel_rows}
            entities = self._entities_out(s, ids, blocks)
            by_id = {e.id: e for e in entities}
            relations = [self._relation_out(r, by_id) for r in rel_rows]
            sugg_rows = list(
                s.scalars(
                    select(KGMergeSuggestionRow)
                    .where(
                        or_(
                            KGMergeSuggestionRow.entity_id.in_(ids),
                            KGMergeSuggestionRow.candidate_id.in_(ids),
                        )
                    )
                    .order_by(KGMergeSuggestionRow.score.desc())
                    .limit(LIST_LIMIT)
                )
            )
            others = {r.candidate_id for r in sugg_rows} | {r.entity_id for r in sugg_rows}
            pool = by_id | {e.id: e for e in self._entities_out(s, others - set(by_id))}
            suggestions = [
                SuggestionOut(
                    id=r.id, score=r.score, entity=pool[r.entity_id], candidate=pool[r.candidate_id]
                )
                for r in sugg_rows
                if r.entity_id in pool and r.candidate_id in pool
            ]
            return DocGraphOut(
                doc_id=doc_id,
                kg_status=doc.kg_status,
                entities=sorted(entities, key=lambda e: (e.type, e.name.casefold())),
                relations=sorted(relations, key=lambda r: (r.block_id, r.type)),
                suggestions=suggestions,
            )

    def entity_detail(self, entity_id: str) -> EntityDetailOut:
        with self._sessions() as s:
            row = self._get(s, entity_id)
            titles = _doc_titles(s)
            mentions = [
                MentionOut(
                    doc_id=m.doc_id,
                    doc_title=titles.get(m.doc_id, ""),
                    block_id=m.block_id,
                    surface=m.surface,
                )
                for m in s.scalars(
                    select(KGMentionRow)
                    .where(KGMentionRow.entity_id == entity_id)
                    .order_by(KGMentionRow.doc_id, KGMentionRow.block_id)
                    .limit(LIST_LIMIT)
                )
            ]
            rel_rows = list(
                s.scalars(
                    select(KGRelationRow)
                    .where(
                        or_(KGRelationRow.src_id == entity_id, KGRelationRow.dst_id == entity_id),
                        KGRelationRow.status != "rejected",
                    )
                    .limit(LIST_LIMIT)
                )
            )
            ends = {r.src_id for r in rel_rows} | {r.dst_id for r in rel_rows} | {entity_id}
            by_id = {e.id: e for e in self._entities_out(s, ends)}
            relations = [self._relation_out(r, by_id, titles) for r in rel_rows]
            return EntityDetailOut(
                entity=by_id.get(entity_id) or self._entity_out(s, row),
                mentions=mentions,
                relations=relations,
            )

    def search_entities(
        self, q: str = "", type_: EntityType | None = None, limit: int = 20
    ) -> list[EntityOut]:
        with self._sessions() as s:
            stmt = select(KGEntityRow.id).distinct()
            n = name_norm(q)
            if n:
                stmt = stmt.join(KGAliasRow, KGAliasRow.entity_id == KGEntityRow.id).where(
                    KGAliasRow.alias_norm.contains(n, autoescape=True)
                )
            if type_ is not None:
                stmt = stmt.where(KGEntityRow.type == type_.value)
            ids = list(s.scalars(stmt.limit(max(1, min(limit, 100)))))
            out = self._entities_out(s, ids)
        # 名称完全相同的在前，其余按名称
        return sorted(out, key=lambda e: (name_norm(e.name) != n, e.name.casefold()))

    def subgraph(self, doc_id: str | None = None, entity_id: str | None = None) -> SubgraphOut:
        """按文档（本篇实体与关系）或实体（它和一跳邻居之间的关系）取子图。"""
        if doc_id:
            g = self.doc_graph(doc_id)
            return SubgraphOut(entities=g.entities, relations=g.relations)
        if not entity_id:
            raise KGEditError("需要 doc_id 或 entity_id")
        detail = self.entity_detail(entity_id)
        with self._sessions() as s:
            ids = {entity_id}
            for r in detail.relations:
                ids |= {r.src_id, r.dst_id}
            entities = self._entities_out(s, ids)
        return SubgraphOut(entities=entities, relations=detail.relations)

    def _entities_out(
        self, s, ids: Iterable[str], blocks: dict[str, list[str]] | None = None
    ) -> list[EntityOut]:
        ids = list(ids)
        if not ids:
            return []
        rows = s.scalars(select(KGEntityRow).where(KGEntityRow.id.in_(ids))).all()
        aliases: dict[str, list[str]] = defaultdict(list)
        for eid, alias in s.execute(
            select(KGAliasRow.entity_id, KGAliasRow.alias).where(KGAliasRow.entity_id.in_(ids))
        ):
            aliases[eid].append(alias)
        counts = dict(
            s.execute(
                select(KGMentionRow.entity_id, func.count(KGMentionRow.doc_id.distinct()))
                .where(KGMentionRow.entity_id.in_(ids))
                .group_by(KGMentionRow.entity_id)
            ).all()
        )
        return [
            EntityOut(
                id=r.id,
                type=r.type,
                name=r.name,
                description=r.description,
                origin=r.origin,
                aliases=sorted(
                    (a for a in aliases[r.id] if a != r.name), key=lambda a: a.casefold()
                ),
                block_ids=sorted((blocks or {}).get(r.id, [])),
                doc_count=counts.get(r.id, 0),
            )
            for r in rows
        ]

    def _entity_out(self, s, row: KGEntityRow) -> EntityOut:
        return self._entities_out(s, [row.id])[0]

    @staticmethod
    def _relation_out(
        r: KGRelationRow, by_id: dict[str, EntityOut], titles: dict[str, str] | None = None
    ) -> RelationOut:
        src, dst = by_id.get(r.src_id), by_id.get(r.dst_id)
        return RelationOut(
            id=r.id,
            type=r.type,
            src_id=r.src_id,
            src_name=src.name if src else r.src_surface,
            src_type=src.type if src else "",
            dst_id=r.dst_id,
            dst_name=dst.name if dst else r.dst_surface,
            dst_type=dst.type if dst else "",
            attrs=r.attrs or {},
            doc_id=r.doc_id,
            doc_title=(titles or {}).get(r.doc_id, ""),
            block_id=r.source_block_id,
            evidence=r.evidence,
            confidence=r.confidence,
            status=r.status,
        )


def _collect_garbage(s) -> None:
    """删掉没有提及、也没有关系的自动实体（重新抽取后不再出现的）。"""
    used = union(
        select(KGMentionRow.entity_id),
        select(KGRelationRow.src_id),
        select(KGRelationRow.dst_id),
    )
    s.execute(delete(KGEntityRow).where(KGEntityRow.origin == "auto", KGEntityRow.id.not_in(used)))


def _doc_titles(s) -> dict[str, str]:
    """doc_id → 文献标题（一个 PDF 挂在多个条目下时取任意一个）。"""
    rows = s.execute(
        select(AttachmentRow.doc_id, ItemRow.title)
        .join(ItemRow, ItemRow.id == AttachmentRow.item_id)
        .where(AttachmentRow.doc_id.is_not(None))
    ).all()
    return {doc_id: title for doc_id, title in rows}
