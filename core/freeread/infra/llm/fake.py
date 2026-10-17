"""确定性的假 provider 与录制回放，用于测试和无密钥开发。

- FakeProvider：默认回显 `[fake:<model>] <最后一条 user 消息>`；可用 `script` 依次给出回复或异常，
  也可从录制文件回放。流式输出把文本按空白切成多个 chunk。
- RecordingProvider：包一层真实 provider，把 (model, messages) → 回复写进 JSON 文件，
  之后 `FakeProvider(replay_file=...)` 可离线回放。
"""

import hashlib
import json
import re
import struct
from collections.abc import AsyncIterator, Callable
from pathlib import Path

from freeread.infra.llm.errors import ProviderError
from freeread.infra.llm.gateway import LLMChunk, LLMResult, Message, Provider, Usage

EMBED_DIM = 8


def request_key(model: str, messages: list[Message]) -> str:
    raw = json.dumps(
        [model, [[m.role, m.content] for m in messages]], ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _echo(model: str, messages: list[Message]) -> str:
    last = next((m.content for m in reversed(messages) if m.role == "user"), "")
    return f"[fake:{model}] {last}"


def _count_tokens(text: str) -> int:
    return len(text.split())


def fake_embedding(text: str) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    ints = struct.unpack(f">{EMBED_DIM}H", digest[: EMBED_DIM * 2])
    return [i / 65535 for i in ints]


class FakeProvider:
    def __init__(
        self,
        name: str = "fake",
        *,
        script: list[str | Exception] | None = None,
        responder: Callable[[str, list[Message]], str] | None = None,
        replay_file: Path | None = None,
    ) -> None:
        self.name = name
        self._script = list(script or [])
        self._responder = responder or _echo
        self._replay: dict[str, str] = {}
        if replay_file is not None:
            self._replay = json.loads(Path(replay_file).read_text(encoding="utf-8"))
        self.calls: list[tuple[str, list[Message], dict]] = []
        self.embed_calls: list[tuple[str, list[str]]] = []

    def _next(self, model: str, messages: list[Message], opts: dict) -> str:
        self.calls.append((model, messages, opts))
        if self._script:
            item = self._script.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        if self._replay:
            key = request_key(model, messages)
            if key not in self._replay:
                raise ProviderError(f"{self.name}: no recorded response for {key[:12]}")
            return self._replay[key]
        return self._responder(model, messages)

    @staticmethod
    def _usage(messages: list[Message], text: str) -> Usage:
        return Usage(sum(_count_tokens(m.content) for m in messages), _count_tokens(text))

    async def complete(self, model: str, messages: list[Message], **opts) -> LLMResult:
        text = self._next(model, messages, opts)
        return LLMResult(text=text, model=model, usage=self._usage(messages, text))

    async def stream(self, model: str, messages: list[Message], **opts) -> AsyncIterator[LLMChunk]:
        text = self._next(model, messages, opts)
        for piece in re.findall(r"\S+\s*|\s+", text):
            yield LLMChunk(delta=piece)
        yield LLMChunk(delta="", done=True, usage=self._usage(messages, text))

    async def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        self.embed_calls.append((model, texts))
        return [fake_embedding(t) for t in texts]


class RecordingProvider:
    """把真实 provider 的非流式 / 流式回复录进 `path`（JSON：请求哈希 → 文本）。"""

    def __init__(self, inner: Provider, path: Path) -> None:
        self.name = inner.name
        self._inner = inner
        self._path = Path(path)
        self._data: dict[str, str] = (
            json.loads(self._path.read_text(encoding="utf-8")) if self._path.exists() else {}
        )

    def _save(self, model: str, messages: list[Message], text: str) -> None:
        self._data[request_key(model, messages)] = text
        self._path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
        )

    async def complete(self, model: str, messages: list[Message], **opts) -> LLMResult:
        result = await self._inner.complete(model, messages, **opts)
        self._save(model, messages, result.text)
        return result

    async def stream(self, model: str, messages: list[Message], **opts) -> AsyncIterator[LLMChunk]:
        parts: list[str] = []
        async for chunk in self._inner.stream(model, messages, **opts):
            parts.append(chunk.delta)
            yield chunk
        self._save(model, messages, "".join(parts))

    async def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        return await self._inner.embed(model, texts)
