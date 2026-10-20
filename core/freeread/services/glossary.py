"""术语表：用户编辑 + 大模型自动抽取，翻译时把块里出现的术语注入提示词。见 docs/m2/glossary.md。

- 全局条目（scope=global）对所有文档生效；文档条目（scope=doc:<doc_id>）只对该文档生效，
  并覆盖全局同名条目；
- 自动抽取（任务 glossary_extract）写入文档条目，origin=auto；重新抽取只替换 auto 条目，
  用户添加或改过的条目（origin=user）不会被覆盖；
- 翻译时只注入在该块里出现的条目（architecture §5.5）。术语表进入渲染后的提示词，
  所以改了术语后同一段落不会命中旧缓存。
"""

import asyncio
import logging
import re
import threading
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import delete, or_, select

from freeread.config import DataPaths
from freeread.domain.ir.models import BlockType
from freeread.domain.summary.parse_json import extract_json
from freeread.infra.db.engine import SessionFactory
from freeread.infra.db.models import GlossaryTermRow
from freeread.infra.jobs.queue import JobOut, JobQueue
from freeread.infra.jobs.worker import JobContext
from freeread.infra.llm.default_gateway import DefaultGateway
from freeread.infra.llm.gateway import TaskKind
from freeread.infra.llm.prompts import PromptRegistry
from freeread.infra.search.text import block_plain_text
from freeread.services.doc_blocks import DocumentNotReady, load_doc
from freeread.services.llm_preflight import check_provider
from freeread.services.settings import SettingsService

log = logging.getLogger(__name__)

PROMPT_ID = "glossary_extract"
EXTRACT_CHARS = 12000  # 送给模型的原文上限（标题、摘要、章节标题优先）
MAX_TERMS = 60  # 一次抽取最多收多少条
MAX_HITS = 24  # 一个块最多注入多少条

Origin = Literal["user", "auto"]


class TermOut(BaseModel):
    id: str
    scope: str  # global | doc:<doc_id>
    lang: str
    source: str
    target: str
    note: str
    origin: Origin
    updated_at: str


class TermIn(BaseModel):
    source: str = Field(min_length=1, max_length=200)
    target: str = Field(min_length=1, max_length=200)
    note: str = Field(default="", max_length=500)
    doc_id: str | None = None  # 不填为全局条目
    lang: str | None = None  # 默认取设置中的目标语言


class TermPatch(BaseModel):
    source: str | None = Field(default=None, min_length=1, max_length=200)
    target: str | None = Field(default=None, min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=500)
    # 文档条目改为全局（"提升为全局"）；全局条目不能改成文档条目
    scope: Literal["global"] | None = None


class GlossaryConflict(ValueError):
    """同一范围、同一语言下已有同名术语。"""


def term_key(term: str) -> str:
    return " ".join(term.split()).casefold()


def doc_scope(doc_id: str) -> str:
    return f"doc:{doc_id}"


_WORDY = re.compile(r"^[\w\s\-./+()'’]+$", re.ASCII)


def _matcher(term: str) -> re.Pattern[str]:
    """拉丁文字按词边界匹配（允许复数 s / es），其他文字（中日韩等）按子串匹配；都不区分大小写。"""
    body = r"\s+".join(re.escape(part) for part in term.split())
    if _WORDY.match(term):
        return re.compile(rf"(?<![A-Za-z0-9]){body}(?:e?s)?(?![A-Za-z0-9])", re.IGNORECASE)
    return re.compile(body, re.IGNORECASE)


@dataclass(frozen=True)
class _Compiled:
    source: str
    target: str
    pattern: re.Pattern[str]


def _parse_terms(text: str) -> list | None:
    try:
        terms = extract_json(text, "terms").get("terms")
    except ValueError:
        return None
    return terms if isinstance(terms, list) else None


def _to_out(row: GlossaryTermRow) -> TermOut:
    return TermOut(
        id=row.id,
        scope=row.scope,
        lang=row.lang,
        source=row.source_term,
        target=row.target_term,
        note=row.note,
        origin=row.origin,  # type: ignore[arg-type]
        updated_at=row.updated_at,
    )


class GlossaryService:
    def __init__(
        self,
        sessions: SessionFactory,
        paths: DataPaths,
        jobs: JobQueue,
        settings: SettingsService,
        gateway: DefaultGateway,
        prompts: PromptRegistry,
    ) -> None:
        self._sessions = sessions
        self._paths = paths
        self._jobs = jobs
        self._settings = settings
        self._gateway = gateway
        self._prompts = prompts
        # (doc_id, lang) → 编译好的条目；任何写操作后整体失效
        self._compiled: dict[tuple[str, str], list[_Compiled]] = {}
        self._lock = threading.Lock()

    def _lang(self, lang: str | None) -> str:
        return lang or self._settings.get().target_lang

    # ------------------------------------------------------------ 查询

    def list_terms(self, lang: str | None = None, doc_id: str | None = None) -> list[TermOut]:
        """不给 doc_id 只列全局条目；给了列全局 + 该文档条目。按原文排序。"""
        lang = self._lang(lang)
        scopes = ["global"] + ([doc_scope(doc_id)] if doc_id else [])
        with self._sessions() as s:
            rows = s.scalars(
                select(GlossaryTermRow).where(
                    GlossaryTermRow.lang == lang, GlossaryTermRow.scope.in_(scopes)
                )
            ).all()
            out = [_to_out(r) for r in rows]
        return sorted(out, key=lambda t: (t.scope == "global", term_key(t.source)))

    def has_auto_terms(self, doc_id: str, lang: str | None = None) -> bool:
        with self._sessions() as s:
            return (
                s.scalar(
                    select(GlossaryTermRow.id)
                    .where(
                        GlossaryTermRow.scope == doc_scope(doc_id),
                        GlossaryTermRow.lang == self._lang(lang),
                        GlossaryTermRow.origin == "auto",
                    )
                    .limit(1)
                )
                is not None
            )

    def terms_for_block(self, doc_id: str, lang: str, text: str) -> list[dict[str, str]]:
        """块里出现的条目，供 translate 提示词使用（[{source, target}]），长术语在前。"""
        hits: list[dict[str, str]] = []
        for term in self._entries(doc_id, lang):
            if term.pattern.search(text):
                hits.append({"source": term.source, "target": term.target})
                if len(hits) >= MAX_HITS:
                    break
        return hits

    def _entries(self, doc_id: str, lang: str) -> list[_Compiled]:
        key = (doc_id, lang)
        with self._lock:
            cached = self._compiled.get(key)
        if cached is not None:
            return cached
        with self._sessions() as s:
            rows = s.scalars(
                select(GlossaryTermRow).where(
                    GlossaryTermRow.lang == lang,
                    GlossaryTermRow.scope.in_(["global", doc_scope(doc_id)]),
                )
            ).all()
            by_key: dict[str, GlossaryTermRow] = {}
            for r in rows:
                if r.term_key not in by_key or r.scope != "global":  # 文档条目覆盖全局
                    by_key[r.term_key] = r
            entries = [
                _Compiled(r.source_term, r.target_term, _matcher(r.source_term))
                for r in by_key.values()
            ]
        entries.sort(key=lambda t: len(t.source), reverse=True)
        with self._lock:
            self._compiled[key] = entries
        return entries

    def _invalidate(self) -> None:
        with self._lock:
            self._compiled.clear()

    # ------------------------------------------------------------ 编辑

    def create(self, body: TermIn, origin: Origin = "user") -> TermOut:
        lang = self._lang(body.lang)
        scope = doc_scope(body.doc_id) if body.doc_id else "global"
        key = term_key(body.source)
        with self._sessions.begin() as s:
            if self._find(s, scope, lang, key) is not None:
                raise GlossaryConflict(f"术语“{body.source.strip()}”已存在")
            row = GlossaryTermRow(
                scope=scope,
                doc_id=body.doc_id,
                lang=lang,
                source_term=body.source.strip(),
                term_key=key,
                target_term=body.target.strip(),
                note=body.note.strip(),
                origin=origin,
            )
            s.add(row)
            s.flush()
            out = _to_out(row)
        self._invalidate()
        return out

    def update(self, term_id: str, patch: TermPatch) -> TermOut:
        """用户改过的条目一律变成 origin=user，以后重新抽取不会覆盖。"""
        with self._sessions.begin() as s:
            row = s.get(GlossaryTermRow, term_id)
            if row is None:
                raise LookupError(f"术语 {term_id} 不存在")
            scope = "global" if patch.scope == "global" else row.scope
            source = patch.source.strip() if patch.source is not None else row.source_term
            key = term_key(source)
            if (scope, key) != (row.scope, row.term_key):
                other = self._find(s, scope, row.lang, key)
                if other is not None and other.id != row.id:
                    raise GlossaryConflict(f"术语“{source}”已存在")
            row.scope = scope
            row.doc_id = None if scope == "global" else row.doc_id
            row.source_term, row.term_key = source, key
            if patch.target is not None:
                row.target_term = patch.target.strip()
            if patch.note is not None:
                row.note = patch.note.strip()
            row.origin = "user"
            s.flush()
            out = _to_out(row)
        self._invalidate()
        return out

    def delete(self, term_id: str) -> bool:
        with self._sessions.begin() as s:
            n = s.execute(delete(GlossaryTermRow).where(GlossaryTermRow.id == term_id)).rowcount
        self._invalidate()
        return n > 0

    @staticmethod
    def _find(s, scope: str, lang: str, key: str) -> GlossaryTermRow | None:
        return s.scalar(
            select(GlossaryTermRow).where(
                GlossaryTermRow.scope == scope,
                GlossaryTermRow.lang == lang,
                GlossaryTermRow.term_key == key,
            )
        )

    # ------------------------------------------------------------ 自动抽取

    def request_extract(self, doc_id: str, lang: str | None = None) -> JobOut:
        """检查文档与模型可用（不可用时抛 LookupError / PreflightError），排队抽取任务。"""
        lang = self._lang(lang)
        load_doc(self._sessions, self._paths, doc_id)
        check_provider(self._gateway, self._settings, TaskKind.GLOSSARY)
        existing = self._jobs.find_active("glossary_extract", doc_id=doc_id, lang=lang)
        return existing or self._jobs.enqueue("glossary_extract", {"doc_id": doc_id, "lang": lang})

    async def run_extract_job(self, ctx: JobContext) -> None:
        doc_id = ctx.job.payload["doc_id"]
        lang = self._lang(ctx.job.payload.get("lang"))
        check_provider(self._gateway, self._settings, TaskKind.GLOSSARY)
        title, content, source_lang = await asyncio.to_thread(self._extract_input, doc_id)
        if not content.strip():
            raise RuntimeError("文档里没有可抽取术语的正文")
        await ctx.report(0.1, "抽取术语")

        from freeread.services.translate import _lang_name  # 避免循环导入

        prompt = self._prompts.get(PROMPT_ID)
        messages = prompt.render(
            source_lang=_lang_name(source_lang),
            target_lang=_lang_name(lang),
            title=title,
            content=content,
        )
        terms: list | None = None
        for attempt in range(2):
            result = await self._gateway.complete(
                TaskKind.GLOSSARY,
                messages,
                prompt_id=prompt.ref,
                doc_id=doc_id,
                use_cache=attempt == 0,  # 坏回复已进缓存，重试必须绕开
            )
            terms = _parse_terms(result.text)
            if terms is not None:
                break
            log.info("glossary %s: invalid reply, attempt %d", doc_id, attempt + 1)
        if terms is None:
            raise RuntimeError("模型没有返回可解析的术语列表")
        added = await asyncio.to_thread(self._store_auto, doc_id, lang, terms)
        await ctx.report(1.0, f"抽取 {added} 条术语")

    def _extract_input(self, doc_id: str) -> tuple[str, str, str | None]:
        try:
            doc = load_doc(self._sessions, self._paths, doc_id)
        except DocumentNotReady as e:
            raise RuntimeError(str(e)) from e
        head: list[str] = []  # 摘要、章节标题优先
        body: list[str] = []
        for b in doc.blocks:
            if b.type == BlockType.HEADING.value:
                head.append(f"## {b.text.strip()}")
            elif b.type == BlockType.ABSTRACT.value:
                head.append(block_plain_text(b.type, b.text, b.inlines, b.html))
            elif b.type != BlockType.TITLE.value:
                text = block_plain_text(b.type, b.text, b.inlines, b.html)
                if len(text) >= 40:
                    body.append(text)
        parts, used = [], 0
        for text in head + body:
            if used + len(text) > EXTRACT_CHARS:
                if used > EXTRACT_CHARS * 0.8:
                    break
                text = text[: EXTRACT_CHARS - used]
            parts.append(text)
            used += len(text)
        return doc.title, "\n\n".join(parts), doc.language

    def _store_auto(self, doc_id: str, lang: str, terms: list) -> int:
        """替换该文档旧的 auto 条目；与用户条目（文档或全局）同名的跳过。"""
        scope = doc_scope(doc_id)
        with self._sessions.begin() as s:
            s.execute(
                delete(GlossaryTermRow).where(
                    GlossaryTermRow.scope == scope,
                    GlossaryTermRow.lang == lang,
                    GlossaryTermRow.origin == "auto",
                )
            )
            taken = set(
                s.scalars(
                    select(GlossaryTermRow.term_key).where(
                        GlossaryTermRow.lang == lang,
                        or_(GlossaryTermRow.scope == scope, GlossaryTermRow.scope == "global"),
                    )
                ).all()
            )
            added = 0
            for raw in terms:
                if not isinstance(raw, dict):
                    continue
                source = str(raw.get("source") or "").strip()
                target = str(raw.get("target") or "").strip()
                if not source or not target or len(source) > 200 or len(target) > 200:
                    continue
                key = term_key(source)
                if key in taken:
                    continue
                taken.add(key)
                s.add(
                    GlossaryTermRow(
                        scope=scope,
                        doc_id=doc_id,
                        lang=lang,
                        source_term=source,
                        term_key=key,
                        target_term=target,
                        note=str(raw.get("note") or "").strip()[:500],
                        origin="auto",
                    )
                )
                added += 1
                if added >= MAX_TERMS:
                    break
        self._invalidate()
        return added
