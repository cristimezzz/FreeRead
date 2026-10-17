"""OpenAI 兼容协议的 provider（OpenAI、DeepSeek、通义、Moonshot、vLLM、Ollama 的 /v1 等）。

只用 httpx，调用 `{base_url}/chat/completions`（含 stream=true 的 SSE）与 `{base_url}/embeddings`。
429 / 5xx / 网络错误抛 RetryableError，由 Gateway 退避重试；本类自己不重试。
"""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from freeread.infra.llm.errors import ProviderError, RetryableError
from freeread.infra.llm.gateway import LLMChunk, LLMResult, Message, Usage

DEFAULT_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
_BODY_SNIPPET = 300


def _usage(data: dict[str, Any] | None) -> Usage | None:
    if not data:
        return None
    return Usage(
        input_tokens=int(data.get("prompt_tokens") or 0),
        output_tokens=int(data.get("completion_tokens") or 0),
    )


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None  # HTTP 日期格式，交给 Gateway 的默认退避


class OpenAICompatibleProvider:
    def __init__(
        self,
        name: str,
        base_url: str,
        api_key: str | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.name = name
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = client or httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)

    def __repr__(self) -> str:
        return f"OpenAICompatibleProvider(name={self.name!r}, base_url={self._base_url!r})"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _redact(self, text: str) -> str:
        return text.replace(self._api_key, "***") if self._api_key else text

    def _error(self, response: httpx.Response, body: str) -> ProviderError:
        snippet = self._redact(body[:_BODY_SNIPPET])
        message = f"{self.name}: HTTP {response.status_code}: {snippet}"
        if response.status_code == 429 or response.status_code >= 500:
            return RetryableError(message, response.status_code, _retry_after(response))
        return ProviderError(message, response.status_code)

    def _transport_error(self, exc: httpx.TransportError) -> RetryableError:
        return RetryableError(f"{self.name}: {type(exc).__name__}: {self._redact(str(exc))}")

    def _body(self, model: str, messages: list[Message], opts: dict[str, Any]) -> dict[str, Any]:
        return {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            **opts,
        }

    async def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._client.post(
                f"{self._base_url}{path}", json=payload, headers=self._headers()
            )
        except httpx.TransportError as exc:
            raise self._transport_error(exc) from None
        if response.status_code >= 400:
            raise self._error(response, response.text)
        try:
            return response.json()
        except ValueError:
            raise ProviderError(f"{self.name}: response is not JSON") from None

    async def complete(self, model: str, messages: list[Message], **opts) -> LLMResult:
        data = await self._post_json("/chat/completions", self._body(model, messages, opts))
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            raise ProviderError(f"{self.name}: unexpected response shape") from None
        return LLMResult(
            text=text,
            model=data.get("model") or model,
            usage=_usage(data.get("usage")) or Usage(0, 0),
        )

    async def stream(self, model: str, messages: list[Message], **opts) -> AsyncIterator[LLMChunk]:
        payload = self._body(model, messages, opts) | {
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        usage: Usage | None = None
        try:
            async with self._client.stream(
                "POST", f"{self._base_url}/chat/completions", json=payload, headers=self._headers()
            ) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode("utf-8", "replace")
                    raise self._error(response, body)
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue  # 空行、注释（": keep-alive"）、event: 行
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        event = json.loads(data)
                    except ValueError:
                        raise ProviderError(f"{self.name}: malformed stream event") from None
                    usage = _usage(event.get("usage")) or usage
                    for choice in event.get("choices") or []:
                        delta = (choice.get("delta") or {}).get("content")
                        if delta:
                            yield LLMChunk(delta=delta)
        except httpx.TransportError as exc:
            raise self._transport_error(exc) from None
        yield LLMChunk(delta="", done=True, usage=usage or Usage(0, 0))

    async def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        data = await self._post_json("/embeddings", {"model": model, "input": texts})
        try:
            items = sorted(data["data"], key=lambda d: d.get("index", 0))
            vectors = [list(map(float, d["embedding"])) for d in items]
        except (KeyError, TypeError, ValueError):
            raise ProviderError(f"{self.name}: unexpected embeddings response shape") from None
        if len(vectors) != len(texts):
            raise ProviderError(f"{self.name}: got {len(vectors)} embeddings for {len(texts)}")
        return vectors

    async def aclose(self) -> None:
        await self._client.aclose()
