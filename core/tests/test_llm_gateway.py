import asyncio

import pytest
from sqlalchemy import select

from freeread.infra.db.models import LLMCacheRow, LLMCallRow
from freeread.infra.llm.default_gateway import DefaultGateway, TokenBucket
from freeread.infra.llm.errors import (
    MissingAPIKey,
    ProviderError,
    RetryableError,
    RouteNotConfigured,
)
from freeread.infra.llm.fake import FakeProvider, RecordingProvider
from freeread.infra.llm.gateway import Message, TaskKind
from freeread.infra.llm.prompts import PromptError, PromptRegistry
from freeread.infra.llm.secrets import SecretStore
from freeread.services.settings import AppSettings, ModelRoute, ProviderConfig

KEY = "sk-test-0123456789abcdef"
MSGS = [Message("system", "translate"), Message("user", "hello world")]


@pytest.fixture
def fake() -> FakeProvider:
    return FakeProvider("p1")


@pytest.fixture
def gateway(ctx, fake):
    ctx.settings.put(
        AppSettings(
            providers=[ProviderConfig(id="p1", name="P1", base_url="http://p1.invalid/v1")],
            routes={
                TaskKind.TRANSLATE: ModelRoute(provider_id="p1", model="m-small"),
                TaskKind.EMBED: ModelRoute(provider_id="p1", model="m-embed"),
            },
        )
    )
    gw = DefaultGateway(
        ctx.settings,
        ctx.sessions,
        SecretStore({"p1": KEY}),
        provider_factory=lambda config, key: fake,
        rate=1000,
        burst=1000,
    )
    gw.sleeps = []

    async def fake_sleep(seconds: float) -> None:
        gw.sleeps.append(seconds)

    gw._sleep = fake_sleep
    return gw


def calls(ctx) -> list[LLMCallRow]:
    with ctx.sessions() as s:
        return list(s.scalars(select(LLMCallRow).order_by(LLMCallRow.id)))


async def test_complete_records_call_and_caches(ctx, gateway, fake):
    r = await gateway.complete(TaskKind.TRANSLATE, MSGS, prompt_id="translate@1", doc_id="d1")
    assert r.text == "[fake:m-small] hello world" and not r.cache_hit
    assert r.usage.input_tokens == 3 and r.usage.output_tokens == 3

    [row] = calls(ctx)
    assert (row.task_kind, row.provider, row.model, row.prompt_id) == (
        "translate",
        "p1",
        "m-small",
        "translate@1",
    )
    assert (row.input_tokens, row.output_tokens, row.cache_hit, row.doc_id) == (3, 3, False, "d1")
    assert row.latency_ms >= 0


async def test_cache_hit_skips_provider_and_is_free(ctx, gateway, fake):
    first = await gateway.complete(TaskKind.TRANSLATE, MSGS, prompt_id="translate@1")
    second = await gateway.complete(TaskKind.TRANSLATE, MSGS, prompt_id="translate@1")
    assert len(fake.calls) == 1
    assert second.cache_hit and second.text == first.text

    rows = calls(ctx)
    assert [r.cache_hit for r in rows] == [False, True]
    assert (rows[1].input_tokens, rows[1].output_tokens) == (0, 0)
    with ctx.sessions() as s:
        [entry] = s.scalars(select(LLMCacheRow))
    assert entry.hit_count == 1


async def test_cache_key_includes_prompt_version_and_opts(gateway, fake):
    await gateway.complete(TaskKind.TRANSLATE, MSGS, prompt_id="translate@1")
    await gateway.complete(TaskKind.TRANSLATE, MSGS, prompt_id="translate@2")
    await gateway.complete(TaskKind.TRANSLATE, MSGS, prompt_id="translate@2", temperature=0.2)
    # doc_id 只用于审计，不影响缓存
    await gateway.complete(TaskKind.TRANSLATE, MSGS, prompt_id="translate@2", doc_id="x")
    assert len(fake.calls) == 3
    assert fake.calls[2][2] == {"temperature": 0.2}


async def test_use_cache_false_bypasses_read(gateway, fake):
    await gateway.complete(TaskKind.TRANSLATE, MSGS, prompt_id="t@1")
    await gateway.complete(TaskKind.TRANSLATE, MSGS, prompt_id="t@1", use_cache=False)
    assert len(fake.calls) == 2


async def test_retry_with_exponential_backoff(ctx, gateway):
    gateway._factory = lambda c, k: FakeProvider(
        "p1", script=[RetryableError("429", 429), RetryableError("502", 502), "ok"]
    )
    r = await gateway.complete(TaskKind.TRANSLATE, MSGS, prompt_id="t@1")
    assert r.text == "ok"
    assert gateway.sleeps == [1.0, 2.0]
    assert len(calls(ctx)) == 1


async def test_retry_honours_retry_after(gateway):
    gateway._factory = lambda c, k: FakeProvider(
        "p1", script=[RetryableError("429", 429, retry_after=7), "ok"]
    )
    await gateway.complete(TaskKind.TRANSLATE, MSGS, prompt_id="t@1")
    assert gateway.sleeps == [7]


async def test_retry_gives_up_after_three_attempts(ctx, gateway):
    provider = FakeProvider("p1", script=[RetryableError(f"e{i}", 503) for i in range(5)])
    gateway._factory = lambda c, k: provider
    with pytest.raises(RetryableError, match="e2"):
        await gateway.complete(TaskKind.TRANSLATE, MSGS, prompt_id="t@1")
    assert len(provider.calls) == 3 and len(gateway.sleeps) == 2
    assert calls(ctx) == []


async def test_non_retryable_error_is_raised_immediately(gateway):
    provider = FakeProvider("p1", script=[ProviderError("401", 401), "ok"])
    gateway._factory = lambda c, k: provider
    with pytest.raises(ProviderError):
        await gateway.complete(TaskKind.TRANSLATE, MSGS, prompt_id="t@1")
    assert len(provider.calls) == 1 and gateway.sleeps == []


async def test_stream_concatenates_and_caches(ctx, gateway, fake):
    chunks = [c async for c in gateway.stream(TaskKind.TRANSLATE, MSGS, prompt_id="t@1")]
    assert len(chunks) > 2
    assert "".join(c.delta for c in chunks) == "[fake:m-small] hello world"
    assert [c.done for c in chunks].count(True) == 1 and chunks[-1].done
    assert chunks[-1].usage.output_tokens == 3

    # 命中缓存：一个 chunk 回放全文，且不再调用 provider
    replay = [c async for c in gateway.stream(TaskKind.TRANSLATE, MSGS, prompt_id="t@1")]
    assert len(replay) == 1 and replay[0].done
    assert replay[0].delta == "[fake:m-small] hello world"
    assert len(fake.calls) == 1
    # 流式与非流式共用缓存
    r = await gateway.complete(TaskKind.TRANSLATE, MSGS, prompt_id="t@1")
    assert r.cache_hit
    assert [r.cache_hit for r in calls(ctx)] == [False, True, True]


async def test_stream_retries_before_first_chunk(gateway):
    gateway._factory = lambda c, k: FakeProvider("p1", script=[RetryableError("503", 503), "a b"])
    chunks = [c async for c in gateway.stream(TaskKind.TRANSLATE, MSGS, prompt_id="t@1")]
    assert "".join(c.delta for c in chunks) == "a b"
    assert gateway.sleeps == [1.0]


async def test_unconfigured_task_raises(ctx, gateway):
    # 只剩嵌入路由时，对话类任务沿回退链也找不到模型（不会落到嵌入模型上）
    settings = ctx.settings.get()
    embed_only = {TaskKind.EMBED: settings.routes[TaskKind.EMBED]}
    ctx.settings.put(settings.model_copy(update={"routes": embed_only}))
    with pytest.raises(RouteNotConfigured, match="kg_extract"):
        await gateway.complete(TaskKind.KG_EXTRACT, MSGS, prompt_id="kg@1")
    with pytest.raises(RouteNotConfigured):
        [c async for c in gateway.stream(TaskKind.KG_EXTRACT, MSGS, prompt_id="kg@1")]


def test_summarize_and_qa_fall_back_to_translate_route(gateway):
    translate = gateway.route(TaskKind.TRANSLATE)
    assert gateway.route(TaskKind.SUMMARIZE) == translate
    assert gateway.route(TaskKind.QA) == translate
    assert gateway.route(TaskKind.KG_EXTRACT) == translate


async def test_missing_key_raises(ctx, fake):
    ctx.settings.put(
        AppSettings(
            providers=[ProviderConfig(id="p1", name="P1", base_url="http://x/v1")],
            routes={TaskKind.TRANSLATE: ModelRoute(provider_id="p1", model="m")},
        )
    )
    gw = DefaultGateway(ctx.settings, ctx.sessions, SecretStore())
    with pytest.raises(MissingAPIKey):
        await gw.complete(TaskKind.TRANSLATE, MSGS, prompt_id="t@1")


async def test_embed_caches_per_text(ctx, gateway, fake):
    v1 = await gateway.embed(["a", "b"])
    v2 = await gateway.embed(["b", "c"])
    assert v1[1] == v2[0] and len(v1[0]) == 8
    assert fake.embed_calls == [("m-embed", ["a", "b"]), ("m-embed", ["c"])]
    assert await gateway.embed(["a", "c"]) == [v1[0], v2[1]]
    assert [r.cache_hit for r in calls(ctx)] == [False, False, True]


class GatedProvider(FakeProvider):
    """调用停在 gate 上，记录同时在跑的调用数的峰值。"""

    def __init__(self) -> None:
        super().__init__("p1")
        self.gate = asyncio.Event()
        self.running = self.peak = 0

    async def complete(self, model, messages, **opts):
        self.running += 1
        self.peak = max(self.peak, self.running)
        try:
            await self.gate.wait()
            return await super().complete(model, messages, **opts)
        finally:
            self.running -= 1


def set_provider_concurrency(ctx, n: int) -> None:
    s = ctx.settings.get()
    ctx.settings.put(
        s.model_copy(
            update={"providers": [s.providers[0].model_copy(update={"max_concurrency": n})]}
        )
    )


async def run_gated(gateway, gated: GatedProvider, n: int, tag: str) -> None:
    tasks = [
        asyncio.create_task(
            gateway.complete(TaskKind.TRANSLATE, [Message("user", f"{tag}{i}")], prompt_id="t@1")
        )
        for i in range(n)
    ]
    for _ in range(20):
        await asyncio.sleep(0)
    gated.gate.set()
    await asyncio.gather(*tasks)
    gated.gate.clear()


async def test_provider_max_concurrency_limits_parallel_calls(ctx, gateway):
    gated = GatedProvider()
    gateway._factory = lambda config, key: gated
    set_provider_concurrency(ctx, 2)
    assert gateway.concurrency(TaskKind.TRANSLATE) == 2
    await run_gated(gateway, gated, 5, "a")
    assert gated.peak == 2

    # 改设置后新请求按新上限
    set_provider_concurrency(ctx, 3)
    gated.peak = 0
    await run_gated(gateway, gated, 5, "b")
    assert gated.peak == 3


def test_provider_max_concurrency_default_and_bounds():
    p = ProviderConfig(id="p1", name="P1", base_url="http://x/v1")
    assert p.max_concurrency == 4
    for bad in (0, 33):
        with pytest.raises(ValueError):
            ProviderConfig(id="p1", name="P1", base_url="http://x/v1", max_concurrency=bad)


def test_unrouted_task_uses_default_concurrency(gateway):
    assert gateway.concurrency(TaskKind.QA) == 4  # QA → 总结 → 翻译，回退到 p1 的默认值
    assert gateway.concurrency(TaskKind.KG_EXTRACT) == 4


async def test_token_bucket_waits_when_empty(monkeypatch):
    now = [0.0]
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)
        now[0] += seconds

    monkeypatch.setattr("freeread.infra.llm.default_gateway.asyncio.sleep", fake_sleep)
    bucket = TokenBucket(rate=2, burst=2, clock=lambda: now[0])
    for _ in range(3):
        await bucket.acquire()
    assert slept == [0.5]


async def test_record_replay(tmp_path):
    path = tmp_path / "rec.json"
    rec = RecordingProvider(FakeProvider(responder=lambda m, msgs: "recorded"), path)
    await rec.complete("m", MSGS)
    replay = FakeProvider(replay_file=path)
    assert (await replay.complete("m", MSGS)).text == "recorded"
    with pytest.raises(ProviderError):
        await replay.complete("m", [Message("user", "other")])


def test_prompts_render_translate():
    prompt = PromptRegistry().get("translate@1")
    assert prompt.ref == "translate@1" and prompt.task is TaskKind.TRANSLATE
    system, user = prompt.render(
        source_lang="en", target_lang="zh-CN", title="T", section_title="S", text="Hello"
    )
    assert system.role == "system" and "zh-CN" in system.content
    assert user.content.endswith("Hello") and "术语表" not in user.content
    _, user = prompt.render(
        source_lang="en",
        target_lang="zh-CN",
        title="T",
        section_title="S",
        text="Hello",
        glossary=[{"source": "transformer", "target": "Transformer"}],
    )
    assert "transformer → Transformer" in user.content
    with pytest.raises(PromptError, match="text"):
        prompt.render(source_lang="en", target_lang="zh", title="T", section_title="S")
    with pytest.raises(PromptError):
        PromptRegistry().get("translate@99")


def test_prompts_dir_when_frozen(monkeypatch, tmp_path):
    """PyInstaller 打包后提示词从 sys._MEIPASS/prompts 读，不依赖仓库目录结构。"""
    import sys

    from freeread.infra.llm import prompts

    assert prompts._default_prompts_dir() == prompts.DEFAULT_PROMPTS_DIR
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert prompts._default_prompts_dir() == tmp_path / "prompts"


def test_prompts_dir_missing_fails_fast(tmp_path):
    with pytest.raises(PromptError, match="not found"):
        PromptRegistry(tmp_path / "missing")
