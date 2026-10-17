import json

import httpx
import pytest

from freeread.infra.llm.errors import ProviderError, RetryableError
from freeread.infra.llm.gateway import Message
from freeread.infra.llm.openai_compatible import OpenAICompatibleProvider

KEY = "sk-live-abcdefghijklmnop"
MSGS = [Message("user", "hi")]


def make(handler) -> tuple[OpenAICompatibleProvider, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(wrapped))
    return OpenAICompatibleProvider("ds", "https://api.example.com/v1/", KEY, client=client), seen


async def test_complete():
    provider, seen = make(
        lambda r: httpx.Response(
            200,
            json={
                "model": "m-2026",
                "choices": [{"message": {"role": "assistant", "content": "你好"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2},
            },
        )
    )
    result = await provider.complete("m", MSGS, temperature=0)
    assert (result.text, result.model, result.usage.input_tokens) == ("你好", "m-2026", 5)
    [req] = seen
    assert str(req.url) == "https://api.example.com/v1/chat/completions"
    assert req.headers["authorization"] == f"Bearer {KEY}"
    body = json.loads(req.content)
    assert body == {"model": "m", "messages": [{"role": "user", "content": "hi"}], "temperature": 0}


async def test_stream_parses_sse_and_usage():
    events = [
        {"choices": [{"delta": {"role": "assistant"}}]},
        {"choices": [{"delta": {"content": "Hel"}}]},
        {"choices": [{"delta": {"content": "lo"}}]},
        {"choices": [], "usage": {"prompt_tokens": 4, "completion_tokens": 2}},
    ]
    sse = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + ": ping\n\ndata: [DONE]\n\n"
    provider, seen = make(lambda r: httpx.Response(200, text=sse))
    chunks = [c async for c in provider.stream("m", MSGS)]
    assert [c.delta for c in chunks] == ["Hel", "lo", ""]
    assert chunks[-1].done and chunks[-1].usage.output_tokens == 2
    body = json.loads(seen[0].content)
    assert body["stream"] is True and body["stream_options"] == {"include_usage": True}


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_retryable_statuses(status):
    provider, _ = make(lambda r: httpx.Response(status, headers={"Retry-After": "3"}, text="busy"))
    with pytest.raises(RetryableError) as info:
        await provider.complete("m", MSGS)
    assert info.value.status_code == status and info.value.retry_after == 3


async def test_client_error_is_not_retryable_and_redacts_key():
    # 有的服务会在错误信息里回显收到的 Authorization
    provider, _ = make(lambda r: httpx.Response(401, json={"error": f"bad key {KEY}"}))
    with pytest.raises(ProviderError) as info:
        await provider.complete("m", MSGS)
    assert not isinstance(info.value, RetryableError)
    assert KEY not in str(info.value) and "***" in str(info.value)


async def test_stream_error_status():
    provider, _ = make(lambda r: httpx.Response(502, text="bad gateway"))
    with pytest.raises(RetryableError, match="502"):
        [c async for c in provider.stream("m", MSGS)]


async def test_network_error_is_retryable():
    def boom(request):
        raise httpx.ConnectError("connection refused")

    provider, _ = make(boom)
    with pytest.raises(RetryableError, match="ConnectError"):
        await provider.complete("m", MSGS)


async def test_embed_orders_by_index():
    provider, seen = make(
        lambda r: httpx.Response(
            200,
            json={"data": [{"index": 1, "embedding": [2, 2]}, {"index": 0, "embedding": [1, 1]}]},
        )
    )
    assert await provider.embed("e", ["a", "b"]) == [[1.0, 1.0], [2.0, 2.0]]
    assert str(seen[0].url).endswith("/v1/embeddings")
    assert json.loads(seen[0].content) == {"model": "e", "input": ["a", "b"]}


def test_repr_hides_key():
    provider, _ = make(lambda r: httpx.Response(200))
    assert KEY not in repr(provider)
