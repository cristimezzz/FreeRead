"""LLMGateway 的默认实现。见 docs/adr/0005-llm-gateway.md 与 docs/01-architecture.md §5.4。

- 路由：每次调用时读设置，TaskKind → (provider, model)；未配置抛 RouteNotConfigured。
- 缓存：键 sha256(provider|model|prompt_id@version|canonical_input)，读写 llm_cache（命中 hit_count+1）。
- 限流：每个 provider 一个令牌桶，外加同时进行的请求数上限（设置里每个服务的 max_concurrency）；
  退避等待不占并发名额，缓存命中不受限。
- 重试：RetryableError（429 / 5xx / 网络）指数退避，最多 3 次尝试；流式只在首个 chunk 之前重试。
- 审计：每次成功的调用（含缓存命中）写一行 llm_calls。失败的调用只记日志，不写表。
- 坏回复不进缓存：complete(accept=...) 校验不过的回复照常返回，但不写 llm_cache；
  缓存里已有的坏回复按未命中处理。流式回复为空时也不写。
- 前缀预热：服务商的前缀缓存（prompt cache）要等第一个请求处理完才建立。system 足够长时，
  同一前缀的第一个请求先单独发出，其余的等它完成（流式等到首个 chunk）再并发。
"""

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
from sqlalchemy import update

from freeread.infra.db.engine import SessionFactory
from freeread.infra.db.models import LLMCacheRow, LLMCallRow
from freeread.infra.llm.errors import MissingAPIKey, RetryableError, RouteNotConfigured
from freeread.infra.llm.gateway import LLMChunk, LLMResult, Message, Provider, TaskKind, Usage
from freeread.infra.llm.openai_compatible import DEFAULT_TIMEOUT, OpenAICompatibleProvider
from freeread.infra.llm.secrets import SecretStore
from freeread.services.settings import (
    DEFAULT_PROVIDER_CONCURRENCY,
    ProviderConfig,
    SettingsService,
)

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
BACKOFF_BASE = 1.0  # 秒；第 n 次重试前等待 BACKOFF_BASE * 2**(n-1)
BACKOFF_MAX = 30.0
DEFAULT_RATE = 5.0  # 每个 provider 每秒请求数
DEFAULT_BURST = 5
EMBED_PROMPT_ID = "embed@1"
WARM_MIN_CHARS = 1000  # system 短于此不值得预热（服务商也不会缓存这么短的前缀）
WARM_TTL = 300.0  # 秒；超过这么久没用过的前缀视为已被服务商淘汰
WARM_WAIT = 10.0  # 秒；等预热请求的上限，超时照常发出
_WARM_KEEP = 256
# 没有单独配置时沿用哪个任务的模型：总结 / 问答默认和翻译用同一个服务（设置里"与翻译相同"）。
# 嵌入不回退：向量要求同一模型，不能悄悄换成聊天模型。
ROUTE_FALLBACK: dict[TaskKind, TaskKind] = {
    TaskKind.SUMMARIZE: TaskKind.TRANSLATE,
    TaskKind.QA: TaskKind.SUMMARIZE,
    TaskKind.GLOSSARY: TaskKind.TRANSLATE,
    TaskKind.KG_EXTRACT: TaskKind.SUMMARIZE,
}

ProviderFactory = Callable[[ProviderConfig, str | None], Provider]


class TokenBucket:
    """异步令牌桶：容量 burst，每秒补充 rate 个。"""

    def __init__(self, rate: float, burst: int, clock: Callable[[], float] = time.monotonic):
        self._rate = rate
        self._capacity = float(burst)
        self._tokens = float(burst)
        self._clock = clock
        self._updated = clock()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = self._clock()
                self._tokens = min(
                    self._capacity, self._tokens + (now - self._updated) * self._rate
                )
                self._updated = now
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                await asyncio.sleep((1 - self._tokens) / self._rate)


class TaskLimiter:
    """一个任务自己的并行度：默认跟随路由到的服务的 max_concurrency，set() 固定下来（评测脚本用）。"""

    def __init__(self, gateway: "DefaultGateway", task: TaskKind, fixed: int | None = None):
        self._gateway = gateway
        self._task = task
        self._fixed = fixed
        self._current: tuple[int, asyncio.Semaphore] | None = None

    def set(self, n: int | None) -> None:
        self._fixed = None if n is None else max(1, n)

    def semaphore(self) -> asyncio.Semaphore:
        # 上限变了就换一个新信号量：进行中的调用在旧的上面自然结束
        n = self._fixed or self._gateway.concurrency(self._task)
        if self._current is None or self._current[0] != n:
            self._current = (n, asyncio.Semaphore(n))
        return self._current[1]


def parses(parse: Callable[[str], Any]) -> Callable[[str], bool]:
    """把"解析失败抛 ValueError"的函数变成 complete(accept=...) 用的判定。"""

    def accept(text: str) -> bool:
        try:
            parse(text)
        except ValueError:
            return False
        return True

    return accept


def canonical_input(messages: list[Message], opts: dict[str, Any]) -> str:
    return json.dumps(
        {"messages": [[m.role, m.content] for m in messages], "opts": opts},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def cache_key(provider_id: str, model: str, prompt_id: str, canonical: str) -> str:
    raw = f"{provider_id}|{model}|{prompt_id}|{canonical}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class DefaultGateway:
    def __init__(
        self,
        settings: SettingsService,
        sessions: SessionFactory,
        secrets: SecretStore,
        *,
        provider_factory: ProviderFactory | None = None,
        rate: float = DEFAULT_RATE,
        burst: int = DEFAULT_BURST,
    ) -> None:
        self._settings = settings
        self._sessions = sessions
        self.secrets = secrets
        self._rate, self._burst = rate, burst
        self._buckets: dict[str, TokenBucket] = {}
        self._limits: dict[str, tuple[int, asyncio.Semaphore]] = {}
        self._http: httpx.AsyncClient | None = None
        self._factory = provider_factory or self._default_factory
        self._sleep = asyncio.sleep  # 测试里替换
        self._clock = time.monotonic  # 测试里替换
        self._warm: dict[str, float] = {}  # 前缀 → 上次成功使用的时间
        self._warming: dict[str, asyncio.Event] = {}  # 正在预热的前缀

    # ---- 前缀预热 ----

    @staticmethod
    def _warm_key(provider_id: str, model: str, messages: list[Message]) -> str | None:
        if not messages or messages[0].role != "system":
            return None
        system = messages[0].content
        if len(system) < WARM_MIN_CHARS:
            return None
        raw = f"{provider_id}|{model}|{system}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    async def _warm_enter(self, key: str | None) -> asyncio.Event | None:
        """前缀还没热：成为预热请求（返回要在结束时交给 _warm_exit 的事件），
        或者等正在预热的那个请求。已经热了直接返回 None。"""
        if key is None:
            return None
        if self._clock() - self._warm.get(key, float("-inf")) < WARM_TTL:
            return None
        pending = self._warming.get(key)
        if pending is None:
            event = self._warming[key] = asyncio.Event()
            return event
        try:
            await asyncio.wait_for(pending.wait(), WARM_WAIT)
        except TimeoutError:
            pass
        return None

    def _warm_exit(self, key: str | None, event: asyncio.Event | None, ok: bool) -> None:
        """预热请求结束（成功、失败、被取消都要调用）：放行等待者。可重复调用。"""
        if key is None:
            return
        if ok:
            if len(self._warm) >= _WARM_KEEP:
                cutoff = self._clock() - WARM_TTL
                self._warm = {k: t for k, t in self._warm.items() if t >= cutoff}
            self._warm[key] = self._clock()
        if event is not None and not event.is_set():
            if self._warming.get(key) is event:
                del self._warming[key]
            event.set()

    # ---- provider ----

    def _default_factory(self, config: ProviderConfig, key: str | None) -> Provider:
        # anthropic 与 ollama 目前都走 OpenAI 兼容端点（Anthropic 的 /v1/chat/completions、
        # Ollama 的 /v1）；原生适配留待后续。
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
        return OpenAICompatibleProvider(config.id, config.base_url, key, client=self._http)

    def provider(self, provider_id: str) -> Provider:
        config = next((p for p in self._settings.get().providers if p.id == provider_id), None)
        if config is None:
            raise RouteNotConfigured(f"provider {provider_id!r} is not configured")
        key = self.secrets.get(provider_id)
        if key is None and config.kind != "ollama":
            raise MissingAPIKey(f"no API key for provider {provider_id!r}")
        return self._factory(config, key)

    def route(self, task: TaskKind) -> tuple[str, str]:
        routes = self._settings.get().routes
        current: TaskKind | None = task
        while current is not None:
            route = routes.get(current)
            if route is not None:
                return route.provider_id, route.model
            current = ROUTE_FALLBACK.get(current)
        raise RouteNotConfigured(f"no model configured for task {task.value!r}")

    def _max_concurrency(self, provider_id: str) -> int:
        config = next((p for p in self._settings.get().providers if p.id == provider_id), None)
        return config.max_concurrency if config else DEFAULT_PROVIDER_CONCURRENCY

    def concurrency(self, task: TaskKind) -> int:
        """任务路由到的服务的并发上限；服务据此决定自己的并行度。"""
        try:
            provider_id, _ = self.route(task)
        except RouteNotConfigured:
            return DEFAULT_PROVIDER_CONCURRENCY
        return self._max_concurrency(provider_id)

    def _slot(self, provider_id: str) -> asyncio.Semaphore:
        # 设置改了就换一个新信号量：进行中的请求在旧的上面自然结束
        n = self._max_concurrency(provider_id)
        current = self._limits.get(provider_id)
        if current is None or current[0] != n:
            current = (n, asyncio.Semaphore(n))
            self._limits[provider_id] = current
        return current[1]

    def _bucket(self, provider_id: str) -> TokenBucket:
        if provider_id not in self._buckets:
            self._buckets[provider_id] = TokenBucket(self._rate, self._burst)
        return self._buckets[provider_id]

    async def _backoff(self, attempt: int, exc: RetryableError) -> None:
        delay = exc.retry_after
        if delay is None:
            delay = BACKOFF_BASE * 2 ** (attempt - 1)
        delay = min(delay, BACKOFF_MAX)
        log.warning(
            "LLM call failed (attempt %d/%d): %s; retry in %.1fs",
            attempt,
            MAX_ATTEMPTS,
            self.secrets.redact(str(exc)),
            delay,
        )
        await self._sleep(delay)

    # ---- 缓存与审计（同步，经 to_thread 调用） ----

    def _cache_get(self, key: str) -> dict[str, Any] | None:
        with self._sessions.begin() as s:
            row = s.get(LLMCacheRow, key)
            if row is None:
                return None
            s.execute(
                update(LLMCacheRow)
                .where(LLMCacheRow.key == key)
                .values(hit_count=LLMCacheRow.hit_count + 1)
            )
            return row.response

    def _cache_put(self, key: str, response: dict[str, Any]) -> None:
        with self._sessions.begin() as s:
            s.merge(LLMCacheRow(key=key, response=response, hit_count=0))

    def _record(
        self,
        *,
        task: TaskKind,
        provider_id: str,
        model: str,
        prompt_id: str | None,
        usage: Usage,
        started: float,
        cache_hit: bool,
        doc_id: str | None,
    ) -> None:
        with self._sessions.begin() as s:
            s.add(
                LLMCallRow(
                    task_kind=task.value,
                    provider=provider_id,
                    model=model,
                    prompt_id=prompt_id,
                    # 缓存命中不计费
                    input_tokens=0 if cache_hit else usage.input_tokens,
                    output_tokens=0 if cache_hit else usage.output_tokens,
                    cached_input_tokens=0 if cache_hit else usage.cached_tokens,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    cache_hit=cache_hit,
                    doc_id=doc_id,
                )
            )

    @staticmethod
    def _audit(
        task: TaskKind,
        provider_id: str,
        model: str,
        prompt_id: str | None,
        started: float,
        doc_id: str | None,
    ) -> dict[str, Any]:
        return {
            "task": task,
            "provider_id": provider_id,
            "model": model,
            "prompt_id": prompt_id,
            "started": started,
            "doc_id": doc_id,
        }

    def _prepare(
        self, task: TaskKind, messages: list[Message], prompt_id: str, opts: dict[str, Any]
    ) -> tuple[str, str, str | None, bool, dict[str, Any], str]:
        provider_id, model = self.route(task)
        doc_id = opts.pop("doc_id", None)
        use_cache = opts.pop("use_cache", True)
        key = cache_key(provider_id, model, prompt_id, canonical_input(messages, opts))
        return provider_id, model, doc_id, use_cache, opts, key

    # ---- LLMGateway ----

    async def complete(
        self,
        task: TaskKind,
        messages: list[Message],
        *,
        prompt_id: str,
        accept: Callable[[str], bool] | None = None,
        **opts,
    ) -> LLMResult:
        """accept：回复是否可用（占位符齐全、JSON 能解析等）。不可用的回复照常返回，
        但不写缓存；缓存里已有的不可用回复按未命中处理。"""
        started = time.perf_counter()
        provider_id, model, doc_id, use_cache, opts, key = self._prepare(
            task, messages, prompt_id, opts
        )
        audit = self._audit(task, provider_id, model, prompt_id, started, doc_id)

        cached = await asyncio.to_thread(self._cache_get, key) if use_cache else None
        if cached is not None and (accept is None or accept(cached["text"])):
            usage = Usage(**cached["usage"])
            await asyncio.to_thread(self._record, usage=usage, cache_hit=True, **audit)
            return LLMResult(cached["text"], cached["model"], usage, cache_hit=True)

        provider = self.provider(provider_id)
        warm_key = self._warm_key(provider_id, model, messages)
        warming = await self._warm_enter(warm_key)
        ok = False
        try:
            for attempt in range(1, MAX_ATTEMPTS + 1):
                try:
                    async with self._slot(provider_id):
                        await self._bucket(provider_id).acquire()
                        result = await provider.complete(model, messages, **opts)
                    break
                except RetryableError as exc:
                    if attempt == MAX_ATTEMPTS:
                        raise
                    await self._backoff(attempt, exc)
            ok = True
        finally:
            self._warm_exit(warm_key, warming, ok)

        if accept is None or accept(result.text):
            await asyncio.to_thread(
                self._cache_put,
                key,
                {"text": result.text, "model": result.model, "usage": vars(result.usage)},
            )
        await asyncio.to_thread(self._record, usage=result.usage, cache_hit=False, **audit)
        return result

    async def stream(
        self, task: TaskKind, messages: list[Message], *, prompt_id: str, **opts
    ) -> AsyncIterator[LLMChunk]:
        started = time.perf_counter()
        provider_id, model, doc_id, use_cache, opts, key = self._prepare(
            task, messages, prompt_id, opts
        )
        audit = self._audit(task, provider_id, model, prompt_id, started, doc_id)

        if use_cache and (cached := await asyncio.to_thread(self._cache_get, key)) is not None:
            usage = Usage(**cached["usage"])
            await asyncio.to_thread(self._record, usage=usage, cache_hit=True, **audit)
            yield LLMChunk(delta=cached["text"], done=True, usage=usage)
            return

        provider = self.provider(provider_id)
        parts: list[str] = []
        usage: Usage | None = None
        warm_key = self._warm_key(provider_id, model, messages)
        warming = await self._warm_enter(warm_key)
        try:
            for attempt in range(1, MAX_ATTEMPTS + 1):
                try:
                    async with self._slot(provider_id):
                        await self._bucket(provider_id).acquire()
                        async for chunk in provider.stream(model, messages, **opts):
                            if chunk.delta:
                                if not parts:
                                    # 首个 chunk 说明服务商已处理完输入：不必让等待者等到整段输出结束
                                    self._warm_exit(warm_key, warming, True)
                                parts.append(chunk.delta)
                                yield LLMChunk(delta=chunk.delta)
                            if chunk.done:
                                usage = chunk.usage
                                break
                    break
                except RetryableError as exc:
                    # 已经向调用方输出过内容就不能透明重试了
                    if parts or attempt == MAX_ATTEMPTS:
                        raise
                    await self._backoff(attempt, exc)
        finally:
            self._warm_exit(warm_key, warming, False)

        text = "".join(parts)
        usage = usage or Usage(0, 0)
        if text.strip():  # 空回复不进缓存，否则同一问题之后一直拿到空
            await asyncio.to_thread(
                self._cache_put, key, {"text": text, "model": model, "usage": vars(usage)}
            )
        await asyncio.to_thread(self._record, usage=usage, cache_hit=False, **audit)
        yield LLMChunk(delta="", done=True, usage=usage)

    async def embed(self, texts: list[str], **opts) -> list[list[float]]:
        """逐条缓存：只把未命中的文本发给 provider。"""
        started = time.perf_counter()
        task = TaskKind.EMBED
        provider_id, model = self.route(task)
        doc_id = opts.pop("doc_id", None)
        keys = [cache_key(provider_id, model, EMBED_PROMPT_ID, t) for t in texts]
        cached = [await asyncio.to_thread(self._cache_get, k) for k in keys]
        missing = [i for i, c in enumerate(cached) if c is None]
        vectors: list[list[float] | None] = [c["embedding"] if c else None for c in cached]

        if missing:
            provider = self.provider(provider_id)
            batch = [texts[i] for i in missing]
            for attempt in range(1, MAX_ATTEMPTS + 1):
                try:
                    async with self._slot(provider_id):
                        await self._bucket(provider_id).acquire()
                        fresh = await provider.embed(model, batch)
                    break
                except RetryableError as exc:
                    if attempt == MAX_ATTEMPTS:
                        raise
                    await self._backoff(attempt, exc)
            for i, vector in zip(missing, fresh, strict=True):
                vectors[i] = vector
                await asyncio.to_thread(self._cache_put, keys[i], {"embedding": vector})

        # embeddings 接口不一定返回 usage；按输入字符数粗估不可靠，这里只记 0。
        audit = self._audit(task, provider_id, model, EMBED_PROMPT_ID, started, doc_id)
        await asyncio.to_thread(self._record, usage=Usage(0, 0), cache_hit=not missing, **audit)
        return [v for v in vectors if v is not None]

    async def test_provider(self, provider_id: str, model: str) -> None:
        """发一条极短请求验证 base_url / 密钥 / 模型名。不走缓存、不重试、不写审计。"""
        provider = self.provider(provider_id)
        async with self._slot(provider_id):
            await self._bucket(provider_id).acquire()
            await provider.complete(model, [Message("user", "Reply with OK.")])

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None
