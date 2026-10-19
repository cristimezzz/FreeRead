"""分层总结。见 docs/01-architecture.md §5.6、docs/m2/summary.md。

1. Map：按一级章节分组（domain/summary/grouping.py），每组生成带块引用的要点（summarize_map@N）；
   提示词与模板无关，换模板重新生成时 Map 调用全部命中 llm_cache；
2. Reduce：把各组要点按模板分节汇总（summarize_reduce@N），每条保留块引用；
3. 校验：引用规范化为 b_NNNN，丢掉文档里不存在的编号，无有效引用的要点标 untraced；
4. 每个 (doc, template, lang) 存一份（summaries），重新生成时替换。
按需生成（用户点"生成"），和翻译一样要先确认向该 provider 发送文档内容。
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable
from typing import Any, Literal, TypeVar

from pydantic import BaseModel
from sqlalchemy import delete, select

from freeread.config import DataPaths
from freeread.domain.summary.citations import clean_point, coverage_stats
from freeread.domain.summary.decoration import DecorationCandidate, decoration_ids
from freeread.domain.summary.grouping import Group, SourceBlock, group_blocks
from freeread.domain.summary.parse_json import extract_json, json_objects
from freeread.infra.db.engine import SessionFactory
from freeread.infra.db.models import SummaryRow
from freeread.infra.llm.default_gateway import DefaultGateway
from freeread.infra.llm.errors import LLMError
from freeread.infra.llm.gateway import Message, TaskKind
from freeread.infra.llm.prompts import Prompt, PromptRegistry
from freeread.infra.search.chunker import approx_tokens
from freeread.infra.search.text import block_plain_text
from freeread.services.doc_blocks import LoadedDoc, load_doc
from freeread.services.llm_preflight import PreflightError, check_provider
from freeread.services.settings import SettingsService
from freeread.services.translate import _lang_name

log = logging.getLogger(__name__)

MAP_PROMPT = "summarize_map"
REDUCE_PROMPT = "summarize_reduce"
MAX_CONCURRENCY = 3
T = TypeVar("T")


class SummaryError(PreflightError):
    """总结无法完成。除 preflight 的 code 外还有 unknown_template / llm_error / bad_output。"""


class TemplateSection(BaseModel):
    key: str
    name: str
    hint: str = ""


class TemplateOut(BaseModel):
    id: str
    version: int
    name: str
    description: str = ""
    sections: list[TemplateSection]


class SummaryPoint(BaseModel):
    text: str
    block_ids: list[str]
    untraced: bool = False


class SummarySection(BaseModel):
    key: str
    name: str
    points: list[SummaryPoint]


class SummaryOut(BaseModel):
    id: str
    doc_id: str
    template_id: str
    lang: str
    model: str
    prompt_version: str
    status: Literal["ok", "stale"]
    created_at: str
    sections: list[SummarySection]
    # points / cited_points / coverage / invalid_ids / groups / failed_groups / elapsed_ms
    stats: dict[str, Any]


class SummaryProgress(BaseModel):
    stage: Literal["map", "reduce"]
    done: int
    total: int
    title: str | None = None


Event = tuple[Literal["progress", "summary"], BaseModel]


class SummaryService:
    def __init__(
        self,
        sessions: SessionFactory,
        paths: DataPaths,
        settings: SettingsService,
        gateway: DefaultGateway,
        prompts: PromptRegistry,
        max_concurrency: int = MAX_CONCURRENCY,
    ) -> None:
        self._sessions = sessions
        self._paths = paths
        self._settings = settings
        self._gateway = gateway
        self._prompts = prompts
        self._sem = asyncio.Semaphore(max_concurrency)

    # ------------------------------------------------------------ 查询

    def templates(self) -> list[TemplateOut]:
        return [TemplateOut.model_validate(t) for t in self._prompts.templates("summary")]

    def template(self, template_id: str) -> TemplateOut:
        found = next((t for t in self.templates() if t.id == template_id), None)
        if found is None:
            raise SummaryError("unknown_template", f"未知的总结模板 {template_id!r}")
        return found

    def load(self, doc_id: str) -> LoadedDoc:
        """API 预检用：文档不存在 LookupError，未解析完成 DocumentNotReady。"""
        return load_doc(self._sessions, self._paths, doc_id)

    def list_for_doc(self, doc_id: str, lang: str | None = None) -> list[SummaryOut]:
        with self._sessions() as s:
            q = select(SummaryRow).where(SummaryRow.doc_id == doc_id)
            if lang:
                q = q.where(SummaryRow.lang == lang)
            return [_to_out(r) for r in s.scalars(q.order_by(SummaryRow.created_at.desc()))]

    # ------------------------------------------------------------ 生成

    async def generate(
        self, doc_id: str, template_id: str, lang: str | None = None
    ) -> AsyncIterator[Event]:
        started = time.perf_counter()
        template = self.template(template_id)
        lang = lang or self._settings.get().target_lang
        doc = await asyncio.to_thread(self.load, doc_id)
        provider_id, model = check_provider(self._gateway, self._settings, TaskKind.SUMMARIZE)
        map_prompt = self._prompts.get(MAP_PROMPT)
        reduce_prompt = self._prompts.get(REDUCE_PROMPT)

        groups = group_blocks(_source_blocks(doc), doc.sections, approx_tokens)
        if not groups:
            raise SummaryError("bad_output", "文档里没有可总结的正文")
        title = doc.title
        target = _lang_name(lang)

        # ---- Map：并发生成各组要点，按完成顺序报告进度
        yield "progress", SummaryProgress(stage="map", done=0, total=len(groups))
        tasks = [
            asyncio.create_task(self._map_group(doc_id, map_prompt, i, g, title, target))
            for i, g in enumerate(groups)
        ]
        results: dict[int, list[dict[str, Any]] | None] = {}
        errors: list[str] = []
        try:
            for done, fut in enumerate(asyncio.as_completed(tasks), 1):
                i, points, error = await fut
                results[i] = points
                if error:
                    errors.append(error)
                yield (
                    "progress",
                    SummaryProgress(
                        stage="map", done=done, total=len(groups), title=groups[i].title
                    ),
                )
        finally:
            for t in tasks:  # 调用方断开：不再等剩下的组
                if not t.done():
                    t.cancel()
        if all(results.get(i) is None for i in range(len(groups))):
            raise SummaryError("llm_error", f"章节摘要全部失败：{errors[-1] if errors else ''}")

        # ---- Reduce：按模板汇总
        yield "progress", SummaryProgress(stage="reduce", done=0, total=1)
        points_text = _format_map_points(groups, results)
        messages = reduce_prompt.render(
            target_lang=target,
            title=title,
            sections=[s.model_dump() for s in template.sections],
            points=points_text,
        )
        existing = {b.block_id for b in doc.blocks}

        def parse_reduce(text: str) -> tuple[list[dict[str, Any]], int]:
            # 模型偶尔把 JSON 结构写坏（如把其他小节写成第一个小节对象里的键）：
            # 依次尝试回复里的每个对象，取第一个能整理出要点的
            for data in json_objects(text):
                sections, invalid = _sections_from(data, template, existing)
                if any(sec["points"] for sec in sections):
                    return sections, invalid
            raise ValueError("汇总结果里没有可用的要点")

        try:
            sections, invalid = await self._complete_json(
                doc_id, reduce_prompt, messages, parse_reduce
            )
        except LLMError as e:
            raise SummaryError("llm_error", f"汇总失败：{e}") from e
        except ValueError as e:
            raise SummaryError("bad_output", f"汇总结果无法解析：{e}") from e
        stats = coverage_stats((p for s in sections for p in s["points"]), invalid) | {
            "groups": len(groups),
            "failed_groups": sum(1 for i in range(len(groups)) if results.get(i) is None),
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }
        prompt_version = f"{map_prompt.ref}+{reduce_prompt.ref}+{template.id}@{template.version}"
        out = await asyncio.to_thread(
            self._save,
            doc_id,
            template.id,
            lang,
            f"{provider_id}/{model}",
            prompt_version,
            {"sections": sections},
            stats,
        )
        yield "summary", out

    async def _map_group(
        self, doc_id: str, prompt: Prompt, index: int, group: Group, title: str, target: str
    ) -> tuple[int, list[dict[str, Any]] | None, str | None]:
        messages = prompt.render(
            target_lang=target, title=title, group_title=group.title, content=group.content
        )
        try:
            async with self._sem:
                data = await self._complete_json(
                    doc_id, prompt, messages, lambda text: extract_json(text, "points")
                )
        except (LLMError, ValueError) as e:
            log.warning("summary map %s / %s failed: %s", doc_id, group.title, e)
            return index, None, str(e)
        allowed = set(group.block_ids)
        points = []
        for raw in data.get("points") or []:
            point, _invalid = clean_point(raw, allowed)
            if point:
                points.append(point)
        return index, points, None

    async def _complete_json(
        self, doc_id: str, prompt: Prompt, messages: list[Message], parse: Callable[[str], T]
    ) -> T:
        """parse 抛 ValueError 时不走缓存重试一次（缓存里是那条坏回复）。"""
        for attempt in range(2):
            result = await self._gateway.complete(
                TaskKind.SUMMARIZE,
                messages,
                prompt_id=prompt.ref,
                doc_id=doc_id,
                use_cache=attempt == 0,
            )
            try:
                return parse(result.text)
            except ValueError:
                if attempt == 1:
                    raise
                log.info("summary %s: %s returned invalid JSON, retrying", doc_id, prompt.ref)
        raise AssertionError("unreachable")

    # ------------------------------------------------------------ 数据库

    def _save(
        self,
        doc_id: str,
        template_id: str,
        lang: str,
        model: str,
        prompt_version: str,
        content: dict[str, Any],
        stats: dict[str, Any],
    ) -> SummaryOut:
        with self._sessions.begin() as s:
            s.execute(
                delete(SummaryRow).where(
                    SummaryRow.doc_id == doc_id,
                    SummaryRow.template_id == template_id,
                    SummaryRow.lang == lang,
                )
            )
            row = SummaryRow(
                doc_id=doc_id,
                scope=f"doc:{doc_id}",
                template_id=template_id,
                lang=lang,
                model=model,
                prompt_version=prompt_version,
                content=content,
                stats=stats,
                status="ok",
            )
            s.add(row)
            s.flush()
            return _to_out(row)


# ---------------------------------------------------------------- 辅助


def _source_blocks(doc: LoadedDoc) -> list[SourceBlock]:
    """送 Map 的块；页眉页脚等页面装饰块的文本置空（不参与，见 domain/summary/decoration.py）。"""
    out = []
    for b in doc.blocks:
        text = (
            b.text if b.type == "heading" else block_plain_text(b.type, b.text, b.inlines, b.html)
        )
        out.append(SourceBlock(b.block_id, b.type, b.section_id, text))
    drop = decoration_ids(
        (
            DecorationCandidate(s.id, s.type, s.text, _anchors(b.anchors))
            for s, b in zip(out, doc.blocks, strict=True)
        ),
        doc.pages,
    )
    for s in out:
        if s.id in drop:
            s.text = ""
    return out


def _anchors(raw: list[dict[str, Any]] | None) -> list[tuple[int, tuple[float, ...]]]:
    return [(a["page"], tuple(a["bbox"])) for a in raw or [] if "page" in a and "bbox" in a]


def _format_map_points(groups: list[Group], results: dict[int, list | None]) -> str:
    lines = []
    for i, g in enumerate(groups):
        points = results.get(i)
        if not points:
            continue
        lines.append(f"### {g.title}")
        for p in points:
            cite = f" [{', '.join(p['block_ids'])}]" if p.get("block_ids") else ""
            lines.append(f"- {p['text']}{cite}")
    return "\n".join(lines)


def _sections_from(
    data: dict[str, Any], template: TemplateOut, existing: set[str]
) -> tuple[list[dict[str, Any]], int]:
    """按模板顺序整理 Reduce 的输出。认不出 key 的小节按位置对应；缺的小节为空。"""
    raw_sections = _raw_sections(data)
    known = {t.key for t in template.sections}
    by_name = {t.name: t.key for t in template.sections}
    by_key: dict[str, dict[str, Any]] = {}
    for pos, sec in enumerate(raw_sections):
        key = str(sec.get("key") or "")
        if key not in known:  # 有的模型把小节名写进 key，或者干脆没写 key
            key = by_name.get(key) or by_name.get(str(sec.get("name") or ""))
        if key is None and pos < len(template.sections):
            key = template.sections[pos].key
        if key is not None:
            by_key.setdefault(key, sec)
    invalid = 0
    out = []
    for t in template.sections:
        raw = by_key.get(t.key)
        points = []
        for p in (raw or {}).get("points") or []:
            point, bad = clean_point(p, existing)
            invalid += bad
            if point:
                points.append(point)
        out.append({"key": t.key, "name": t.name, "points": points})
    return out, invalid


def _flatten(obj: dict[str, Any]) -> list[dict[str, Any]]:
    """{"key": k, "points": [...], "<其他 key>": [...]} → 每个 key 一个小节。"""
    out = []
    if "points" in obj:
        out.append({"key": obj.get("key"), "name": obj.get("name"), "points": obj["points"]})
    out += [
        {"key": k, "points": v}
        for k, v in obj.items()
        if k not in ("key", "name", "points", "sections") and isinstance(v, list)
    ]
    return out


def _raw_sections(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Reduce 输出的几种形状都整理成 [{key, name?, points}]：
    标准的 sections 列表、sections 写成 {key: points}、小节对象里混入其他小节、整个对象就是一个小节。"""
    secs = data.get("sections")
    if isinstance(secs, list):
        return [part for s in secs if isinstance(s, dict) for part in _flatten(s)]
    if isinstance(secs, dict):
        return [{"key": k, "points": v} for k, v in secs.items() if isinstance(v, list)]
    return _flatten(data)


def _to_out(row: SummaryRow) -> SummaryOut:
    return SummaryOut(
        id=row.id,
        doc_id=row.doc_id,
        template_id=row.template_id,
        lang=row.lang,
        model=row.model,
        prompt_version=row.prompt_version,
        status=row.status,
        created_at=row.created_at,
        sections=row.content.get("sections", []),
        stats=row.stats or {},
    )


def migrate_summaries(s, doc_id: str, mapping: dict[str, str]) -> int:
    """重新解析后改写引用（与译文迁移同一事务，见 ParseService._store）。

    映射不上的引用去掉，要点失去全部引用时标 untraced；有任何引用丢失的总结标 stale。
    返回标 stale 的总结数。
    """
    stale = 0
    for row in s.scalars(select(SummaryRow).where(SummaryRow.doc_id == doc_id)):
        lost = False
        sections = []
        for sec in row.content.get("sections", []):
            points = []
            for p in sec.get("points", []):
                ids = [mapping[i] for i in p.get("block_ids", []) if i in mapping]
                lost |= len(ids) < len(p.get("block_ids", []))
                point = {"text": p["text"], "block_ids": ids}
                if not ids:
                    point["untraced"] = True
                points.append(point)
            sections.append(sec | {"points": points})
        row.content = {"sections": sections}
        row.stats = (row.stats or {}) | coverage_stats(
            (p for sec in sections for p in sec["points"]), (row.stats or {}).get("invalid_ids", 0)
        )
        if lost:
            row.status = "stale"
            stale += 1
    return stale
