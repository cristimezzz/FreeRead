"""块级翻译。见 docs/01-architecture.md §5.5。

1. 前端上报可视区域的 block_id → 已有译文立即返回，其余按阅读顺序、受限并发调用 LLM；
2. 占位保护（domain/translate/placeholders.py）：校验失败不走缓存重试一次，仍失败记
   needs_review，译文回退为原文；
3. 上下文：论文标题、当前章节标题、上一段原文、块里出现的术语（prompt translate@N）；
4. 结果写入 translations（同一块同一语言只有一行 is_active），并逐块产出事件。
首次向某个 provider 发送文档内容前，必须由用户在前端确认（settings.consented_providers）。

整篇翻译是后台任务 translate_doc：按阅读顺序分批调用 translate_blocks，和阅读器的请求共用
并发上限与"同一块只翻一次"的去重。
"""

import asyncio
import logging
from collections import Counter
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel
from sqlalchemy import select, update

from freeread.domain.ir.models import TRANSLATABLE_TYPES, BlockType
from freeread.domain.translate.placeholders import PlaceholderMismatch, protect, restore
from freeread.infra.db.engine import SessionFactory
from freeread.infra.db.models import BlockRow, DocumentRow, TranslationRow
from freeread.infra.jobs.queue import JobOut, JobQueue
from freeread.infra.jobs.worker import JobContext
from freeread.infra.llm.default_gateway import DefaultGateway, TaskLimiter
from freeread.infra.llm.errors import LLMError, MissingAPIKey, RouteNotConfigured
from freeread.infra.llm.gateway import TaskKind
from freeread.infra.llm.prompts import PromptRegistry
from freeread.services.llm_preflight import PreflightError, check_provider
from freeread.services.settings import SettingsService

if TYPE_CHECKING:
    from freeread.services.glossary import GlossaryService

log = logging.getLogger(__name__)

PROMPT_ID = "translate"
DOC_BATCH = 30  # 整篇翻译每批的块数
TRANSLATABLE = frozenset(t.value for t in TRANSLATABLE_TYPES)
LANG_NAMES = {
    "zh": "中文",
    "zh-CN": "简体中文",
    "zh-TW": "繁体中文",
    "en": "英文",
    "ja": "日文",
    "ko": "韩文",
    "de": "德文",
    "fr": "法文",
}


class TranslationOut(BaseModel):
    block_id: str
    lang: str
    text: str  # 含 IR 占位符（⟦EQ1⟧ 等），按块的 inlines 渲染
    status: Literal["ok", "needs_review"]
    model: str
    prompt_version: str
    created_at: str


class TranslationEvent(BaseModel):
    """SSE `translation` 事件。status=skipped 表示该块不需要翻译（公式、图、参考文献等）。"""

    block_id: str
    status: Literal["ok", "needs_review", "skipped", "error"]
    text: str | None = None
    cached: bool = False
    message: str | None = None


# 整批请求无法进行（未配置模型、缺密钥、未确认隐私提示）。code 供前端区分处理。
TranslateError = PreflightError


@dataclass
class _Block:
    id: str
    type: str
    section_id: str | None
    text: str


@dataclass
class _DocContext:
    doc_id: str
    title: str
    source_lang: str | None
    blocks: dict[str, _Block]
    order: list[str]
    section_titles: dict[str, str]


def _lang_name(code: str | None) -> str:
    if not code:
        return "原文语言"
    return LANG_NAMES.get(code) or LANG_NAMES.get(code.split("-")[0]) or code


def _same_language(source: str | None, target: str) -> bool:
    return bool(source) and source.split("-")[0].lower() == target.split("-")[0].lower()


class TranslateService:
    def __init__(
        self,
        sessions: SessionFactory,
        settings: SettingsService,
        gateway: DefaultGateway,
        prompts: PromptRegistry,
        max_concurrency: int | None = None,
        *,
        jobs: JobQueue | None = None,
        glossary: "GlossaryService | None" = None,
    ) -> None:
        self._sessions = sessions
        self._jobs = jobs
        self.glossary = glossary
        self._settings = settings
        self._gateway = gateway
        self._prompts = prompts
        # 全局并发上限：多个请求（多个窗口 / 快速滚动）共享；默认跟随翻译服务的设置
        self._limit = TaskLimiter(gateway, TaskKind.TRANSLATE, max_concurrency)
        # 同一块同一语言正在翻译时，后来的请求等它的结果，不重复调用
        self._inflight: dict[tuple[str, str, str], asyncio.Task[TranslationEvent]] = {}
        self._waiters: Counter[tuple[str, str, str]] = Counter()

    # ------------------------------------------------------------ 查询

    def list_for_doc(self, doc_id: str, lang: str) -> list[TranslationOut]:
        """离线可读：只查本地库，不访问网络。"""
        with self._sessions() as s:
            rows = s.scalars(
                select(TranslationRow).where(
                    TranslationRow.doc_id == doc_id,
                    TranslationRow.lang == lang,
                    TranslationRow.is_active.is_(True),
                    TranslationRow.status != "stale",
                )
            ).all()
            return [TranslationOut.model_validate(r, from_attributes=True) for r in rows]

    # ------------------------------------------------------------ 翻译

    def preflight(self, lang: str | None) -> tuple[str, str, str]:
        """检查路由、密钥与隐私确认，返回 (provider_id, model, lang)。不满足时抛 TranslateError。"""
        lang = lang or self._settings.get().target_lang
        provider_id, model = check_provider(self._gateway, self._settings, TaskKind.TRANSLATE)
        return provider_id, model, lang

    async def translate_blocks(
        self, doc_id: str, block_ids: list[str], lang: str | None = None
    ) -> AsyncIterator[TranslationEvent]:
        """按请求顺序先产出已有译文，再按完成顺序产出新译文。调用方断开时取消未完成的块。"""
        doc = await asyncio.to_thread(self._load, doc_id)
        lang = lang or self._settings.get().target_lang
        wanted = list(dict.fromkeys(b for b in block_ids if b in doc.blocks))

        existing = {t.block_id: t for t in await asyncio.to_thread(self.list_for_doc, doc_id, lang)}
        todo: list[_Block] = []
        for bid in wanted:
            block = doc.blocks[bid]
            if bid in existing:
                t = existing[bid]
                yield TranslationEvent(block_id=bid, status=t.status, text=t.text, cached=True)
            elif (
                block.type not in TRANSLATABLE
                or not block.text.strip()
                or _same_language(doc.source_lang, lang)
            ):
                yield TranslationEvent(block_id=bid, status="skipped")
            else:
                todo.append(block)
        if not todo:
            return

        provider_id, model, lang = self.preflight(lang)
        keys = [(doc_id, block.id, lang) for block in todo]
        tasks = [self._task(doc, block, lang, provider_id, model) for block in todo]
        try:
            for fut in asyncio.as_completed(tasks):
                yield await fut
        finally:
            # 调用方断开（滚走了）：还没完成、也没有别的请求在等的块就不翻了
            for key, task in zip(keys, tasks, strict=True):
                self._waiters[key] -= 1
                if self._waiters[key] <= 0:
                    del self._waiters[key]
                    if not task.done():
                        task.cancel()

    def _task(
        self, doc: _DocContext, block: _Block, lang: str, provider_id: str, model: str
    ) -> asyncio.Task[TranslationEvent]:
        key = (doc.doc_id, block.id, lang)
        task = self._inflight.get(key)
        if task is None or task.done():
            task = asyncio.create_task(self._translate_one(doc, block, lang, provider_id, model))
            self._inflight[key] = task
            task.add_done_callback(
                lambda t, k=key: self._inflight.pop(k, None) if self._inflight.get(k) is t else None
            )
        self._waiters[key] += 1
        return task

    async def _translate_one(
        self, doc: _DocContext, block: _Block, lang: str, provider_id: str, model: str
    ) -> TranslationEvent:
        prompt = self._prompts.get(PROMPT_ID)
        protected = protect(block.text)
        glossary = (
            await asyncio.to_thread(self.glossary.terms_for_block, doc.doc_id, lang, block.text)
            if self.glossary
            else []
        )
        messages = prompt.render(
            source_lang=_lang_name(doc.source_lang),
            target_lang=_lang_name(lang),
            title=doc.title,
            section_title=doc.section_titles.get(block.section_id or "", ""),
            prev_text=self._prev_text(doc, block.id),
            text=protected.text,
            glossary=glossary,
        )
        status, text = "ok", None
        async with self._limit.semaphore():
            for attempt in range(2):
                try:
                    result = await self._gateway.complete(
                        TaskKind.TRANSLATE,
                        messages,
                        prompt_id=prompt.ref,
                        doc_id=doc.doc_id,
                        # 第一次的结果已进缓存；重试必须绕开，否则拿回同一个错误译文
                        use_cache=attempt == 0,
                    )
                except (RouteNotConfigured, MissingAPIKey) as e:
                    return TranslationEvent(block_id=block.id, status="error", message=str(e))
                except LLMError as e:
                    log.warning("translate %s/%s failed: %s", doc.doc_id, block.id, e)
                    return TranslationEvent(block_id=block.id, status="error", message=str(e))
                try:
                    text = restore(protected, result.text.strip())
                    break
                except PlaceholderMismatch as e:
                    log.info("%s/%s attempt %d: %s", doc.doc_id, block.id, attempt + 1, e)
            else:
                status, text = "needs_review", block.text  # 回退原文

        try:
            await asyncio.to_thread(
                self._save,
                doc.doc_id,
                block.id,
                lang,
                f"{provider_id}/{model}",
                prompt.ref,
                text,
                status,
            )
        except Exception as e:  # 写库失败只影响这一块，不能中断整批的 SSE
            log.exception("save translation %s/%s failed", doc.doc_id, block.id)
            return TranslationEvent(block_id=block.id, status="error", message=str(e))
        return TranslationEvent(block_id=block.id, status=status, text=text)

    # ------------------------------------------------------------ 整篇翻译

    def request_doc(self, doc_id: str, lang: str | None = None) -> JobOut:
        """排队整篇翻译。文档未就绪抛 LookupError，模型不可用抛 TranslateError。

        设置了 glossary.auto_extract 且该文档还没有自动抽取的术语时，先排一个抽取任务，
        翻译任务等它完成（抽取失败则翻译任务被取消）。
        """
        assert self._jobs is not None
        self._load(doc_id)
        _, _, lang = self.preflight(lang)
        existing = self._jobs.find_active("translate_doc", doc_id=doc_id, lang=lang)
        if existing:
            return existing
        depends_on = None
        if (
            self.glossary is not None
            and self._settings.get().glossary.auto_extract
            and not self.glossary.has_auto_terms(doc_id, lang)
        ):
            depends_on = self.glossary.request_extract(doc_id, lang).id
        return self._jobs.enqueue("translate_doc", {"doc_id": doc_id, "lang": lang}, depends_on)

    async def run_doc_job(self, ctx: JobContext) -> None:
        doc_id = ctx.job.payload["doc_id"]
        lang = ctx.job.payload.get("lang") or self._settings.get().target_lang
        doc = await asyncio.to_thread(self._load, doc_id)
        if _same_language(doc.source_lang, lang):
            await ctx.report(1.0, "原文已是目标语言")
            return
        self.preflight(lang)
        done_ids = {t.block_id for t in await asyncio.to_thread(self.list_for_doc, doc_id, lang)}
        todo = [
            bid
            for bid in doc.order
            if bid not in done_ids
            and doc.blocks[bid].type in TRANSLATABLE
            and doc.blocks[bid].text.strip()
        ]
        total = len(todo)
        if not total:
            await ctx.report(1.0, "全文已翻译")
            return
        counts: Counter[str] = Counter()
        await ctx.report(0.0, f"0 / {total} 段")
        for start in range(0, total, DOC_BATCH):
            async for event in self.translate_blocks(doc_id, todo[start : start + DOC_BATCH], lang):
                counts[event.status] += 1
            n = min(start + DOC_BATCH, total)
            await ctx.report(n / total, f"{n} / {total} 段")
        translated = counts["ok"] + counts["needs_review"]
        if counts["error"] and not translated:
            raise RuntimeError(f"{counts['error']} 段全部翻译失败")
        parts = [f"翻译 {translated} 段"]
        if counts["needs_review"]:
            parts.append(f"{counts['needs_review']} 段需要复核")
        if counts["error"]:
            parts.append(f"{counts['error']} 段失败")
        await ctx.report(1.0, "，".join(parts))

    @staticmethod
    def _prev_text(doc: _DocContext, block_id: str) -> str:
        i = doc.order.index(block_id)
        for bid in reversed(doc.order[:i]):
            b = doc.blocks[bid]
            if b.type in (BlockType.PARAGRAPH, BlockType.ABSTRACT, BlockType.LIST_ITEM):
                return b.text
            if b.type == BlockType.HEADING:
                return ""  # 新章节开头不带上一章的内容
        return ""

    # ------------------------------------------------------------ 数据库

    def _load(self, doc_id: str) -> _DocContext:
        with self._sessions() as s:
            doc = s.get(DocumentRow, doc_id)
            if doc is None:
                raise LookupError(f"文档 {doc_id} 不存在")
            if doc.parse_status != "ready":
                raise LookupError(f"文档 {doc_id} 尚未解析完成")
            rows = s.scalars(
                select(BlockRow).where(BlockRow.doc_id == doc_id).order_by(BlockRow.ord)
            ).all()
            blocks = {r.block_id: _Block(r.block_id, r.type, r.section_id, r.text) for r in rows}
            language = doc.language
        order = list(blocks)
        title = next((b.text for b in blocks.values() if b.type == BlockType.TITLE), "")
        section_titles: dict[str, str] = {}
        for b in blocks.values():
            if b.type == BlockType.HEADING and b.section_id and b.section_id not in section_titles:
                section_titles[b.section_id] = b.text
        return _DocContext(doc_id, title, language, blocks, order, section_titles)

    def _save(
        self,
        doc_id: str,
        block_id: str,
        lang: str,
        model: str,
        prompt_version: str,
        text: str,
        status: str,
    ) -> None:
        with self._sessions.begin() as s:
            s.execute(
                update(TranslationRow)
                .where(
                    TranslationRow.doc_id == doc_id,
                    TranslationRow.block_id == block_id,
                    TranslationRow.lang == lang,
                )
                .values(is_active=False)
            )
            row = s.scalar(
                select(TranslationRow).where(
                    TranslationRow.doc_id == doc_id,
                    TranslationRow.block_id == block_id,
                    TranslationRow.lang == lang,
                    TranslationRow.model == model,
                    TranslationRow.prompt_version == prompt_version,
                )
            )
            if row is None:
                row = TranslationRow(
                    doc_id=doc_id,
                    block_id=block_id,
                    lang=lang,
                    model=model,
                    prompt_version=prompt_version,
                )
                s.add(row)
            row.text = text
            row.status = status
            row.is_active = True
