import asyncio

import pytest
import yaml
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
from freeread.infra.llm.gateway import LLMResult, Message, TaskKind, Usage
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
    prompt = PromptRegistry().get("translate@2")
    assert prompt.ref == "translate@2" and prompt.task is TaskKind.TRANSLATE
    doc = {"source_lang": "en", "target_lang": "zh-CN", "title": "My Paper"}
    system, user = prompt.render(**doc, section_title="S", text="Hello")
    assert system.role == "system" and "zh-CN" in system.content and "My Paper" in system.content
    assert user.content.endswith("Hello") and "术语" not in user.content
    term = {"source": "transformer", "target": "Transformer"}
    system2, user = prompt.render(
        **doc,
        abstract="An abstract.",
        glossary=[term],
        section_title="S",
        text="Hello",
        hits=[term],
    )
    assert "An abstract." in system2.content and "transformer → Transformer" in system2.content
    assert "transformer → Transformer" in user.content
    # 段落级变量只影响 user：system 不变，前缀缓存才能命中
    system3, _ = prompt.render(
        **doc, section_title="Other", text="Bye", prev_text="Before", hits=[term]
    )
    assert system3 == system
    with pytest.raises(PromptError, match="text"):
        prompt.render(**doc, section_title="S")
    with pytest.raises(PromptError):
        PromptRegistry().get("translate@99")


def test_prompt_prefix_only_uses_document_level_variables():
    """system / context 是服务商前缀缓存的前缀：不能引用逐次调用变化的变量。"""
    from jinja2 import Environment, meta

    from freeread.infra.llm.prompts import DEFAULT_PROMPTS_DIR

    stable = {"source_lang", "target_lang", "title", "abstract", "glossary", "fulltext"}
    env = Environment()
    for path in sorted(DEFAULT_PROMPTS_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        prefix = (data.get("system") or "") + (data.get("context") or "")
        used = meta.find_undeclared_variables(env.parse(prefix))
        assert used <= stable, f"{path.name}: {sorted(used - stable)} in system/context"


def test_prompt_history_goes_between_system_and_user():
    prompt = PromptRegistry().get("qa_answer")
    turn = [prompt.user_message(question="Q1"), Message("assistant", "A1")]
    messages = prompt.render(
        history=turn, target_lang="中文", title="T", fulltext="[b_0001] text", question="Q2"
    )
    assert [m.role for m in messages] == ["system", "user", "assistant", "user"]
    assert "[b_0001] text" in messages[0].content and messages[1].content == "问题：Q1"
    first = prompt.render(target_lang="中文", title="T", fulltext="[b_0001] text", question="Q1")
    assert messages[:2] == first  # 上一问的请求是这一问的前缀


# ---------------------------------------------------------------- 坏回复不进缓存


async def test_rejected_reply_is_returned_but_not_cached(ctx, gateway, fake):
    fake._script = ["bad", "good"]
    ok = lambda text: text == "good"
    r = await gateway.complete(TaskKind.TRANSLATE, MSGS, prompt_id="t@1", accept=ok)
    assert r.text == "bad"
    with ctx.sessions() as s:
        assert s.scalars(select(LLMCacheRow)).all() == []
    r = await gateway.complete(TaskKind.TRANSLATE, MSGS, prompt_id="t@1", accept=ok)
    assert r.text == "good" and not r.cache_hit
    r = await gateway.complete(TaskKind.TRANSLATE, MSGS, prompt_id="t@1", accept=ok)
    assert r.cache_hit and len(fake.calls) == 2
    assert len(calls(ctx)) == 3  # 被拒的回复也花了钱，照常记账


async def test_cached_reply_that_fails_accept_is_treated_as_a_miss(gateway, fake):
    fake._script = ["old bad reply", "good"]
    await gateway.complete(TaskKind.TRANSLATE, MSGS, prompt_id="t@1")  # 旧版本缓存下来的坏回复
    r = await gateway.complete(
        TaskKind.TRANSLATE, MSGS, prompt_id="t@1", accept=lambda text: text == "good"
    )
    assert r.text == "good" and not r.cache_hit
    assert (await gateway.complete(TaskKind.TRANSLATE, MSGS, prompt_id="t@1")).text == "good"


async def test_empty_stream_is_not_cached(ctx, gateway, fake):
    fake._script = ["", "answer"]
    chunks = [c async for c in gateway.stream(TaskKind.TRANSLATE, MSGS, prompt_id="t@1")]
    assert "".join(c.delta for c in chunks) == ""
    chunks = [c async for c in gateway.stream(TaskKind.TRANSLATE, MSGS, prompt_id="t@1")]
    assert "".join(c.delta for c in chunks) == "answer" and len(fake.calls) == 2


# ---------------------------------------------------------------- 前缀缓存：计量与预热


async def test_provider_cached_tokens_are_recorded(ctx, gateway):
    class Cached(FakeProvider):
        async def complete(self, model, messages, **opts):
            return LLMResult("ok", model, Usage(100, 5, cached_tokens=80))

    gateway._factory = lambda c, k: Cached("p1")
    r = await gateway.complete(TaskKind.TRANSLATE, MSGS, prompt_id="t@1")
    assert r.usage.cached_tokens == 80
    hit = await gateway.complete(TaskKind.TRANSLATE, MSGS, prompt_id="t@1")
    assert hit.cache_hit and hit.usage.cached_tokens == 80
    rows = calls(ctx)
    assert [(r.input_tokens, r.cached_input_tokens) for r in rows] == [(100, 80), (0, 0)]


LONG_SYSTEM = Message("system", "rules " * 400)


def warm_msgs(i: int) -> list[Message]:
    return [LONG_SYSTEM, Message("user", f"block {i}")]


async def settle() -> None:
    for _ in range(50):
        await asyncio.sleep(0.001)


async def test_first_request_warms_the_prefix_before_the_rest_fan_out(gateway):
    gated = GatedProvider()
    gateway._factory = lambda config, key: gated
    tasks = [
        asyncio.create_task(gateway.complete(TaskKind.TRANSLATE, warm_msgs(i), prompt_id="t@1"))
        for i in range(4)
    ]
    await settle()
    assert gated.running == 1  # 其余三个在等第一个把前缀缓存建起来
    gated.gate.set()
    await asyncio.gather(*tasks)

    # 前缀已经热了：新请求不再排队，直接并发
    gated.gate.clear()
    gated.peak = 0
    tasks = [
        asyncio.create_task(gateway.complete(TaskKind.TRANSLATE, warm_msgs(i), prompt_id="t@1"))
        for i in range(4, 7)
    ]
    await settle()
    assert gated.running == 3
    gated.gate.set()
    await asyncio.gather(*tasks)

    # 太久没用：服务商那边多半已经淘汰，重新预热
    now = gateway._clock()
    gateway._clock = lambda: now + 301
    gated.gate.clear()
    tasks = [
        asyncio.create_task(gateway.complete(TaskKind.TRANSLATE, warm_msgs(i), prompt_id="t@1"))
        for i in range(7, 9)
    ]
    await settle()
    assert gated.running == 1
    gated.gate.set()
    await asyncio.gather(*tasks)


async def test_failed_or_cancelled_warm_up_releases_the_waiters(gateway):
    class FailFirst(GatedProvider):
        async def complete(self, model, messages, **opts):
            first = not self.calls and self.running == 0
            result = await super().complete(model, messages, **opts)
            if first:
                raise ProviderError("401", 401)
            return result

    failing = FailFirst()
    gateway._factory = lambda config, key: failing
    tasks = [
        asyncio.create_task(gateway.complete(TaskKind.TRANSLATE, warm_msgs(i), prompt_id="t@1"))
        for i in range(3)
    ]
    await settle()
    assert failing.running == 1
    failing.gate.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    assert isinstance(results[0], ProviderError)
    assert [r.text for r in results[1:]] == ["[fake:m-small] block 1", "[fake:m-small] block 2"]

    # 预热请求被取消（用户滚走了）：等待者照常继续
    gated = GatedProvider()
    gateway._factory = lambda config, key: gated
    other = [Message("system", "other " * 400), Message("user", "x")]
    leader = asyncio.create_task(gateway.complete(TaskKind.TRANSLATE, other, prompt_id="t@1"))
    await settle()
    follower = asyncio.create_task(
        gateway.complete(TaskKind.TRANSLATE, [other[0], Message("user", "y")], prompt_id="t@1")
    )
    await settle()
    assert gated.running == 1
    leader.cancel()
    await settle()
    assert gated.running == 1  # 现在跑的是 follower
    gated.gate.set()
    assert (await follower).text == "[fake:m-small] y"
    assert gateway._warming == {}


async def test_short_system_prompts_are_not_gated(gateway):
    gated = GatedProvider()
    gateway._factory = lambda config, key: gated
    await run_gated(gateway, gated, 3, "s")
    assert gated.peak == 3


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
