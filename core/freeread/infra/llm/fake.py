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


_BLOCK_LINE_RE = re.compile(r"^\[(b_\d+)\] (.+)$", re.MULTILINE)
_POINT_RE = re.compile(r"^- (.+?)(?: \[(b_[\d, b_]+)\])?$", re.MULTILINE)
_SECTION_KEY_RE = re.compile(r"^- (\w+)（", re.MULTILINE)


def summary_responder(model: str, messages: list[Message]) -> str:
    """看得懂 summarize_map / summarize_reduce 提示词的确定性回复（测试与 --fake 评测用）。

    Map：每个块一个要点，引用该块；Reduce：把输入要点轮流分到各小节，保留引用。
    其他请求按 _echo 处理。
    """
    user = messages[-1].content
    if '"sections"' in messages[0].content:
        keys = _SECTION_KEY_RE.findall(user)
        sections = [{"key": k, "points": []} for k in keys]
        found = [
            (text, re.findall(r"b_\d+", ids or ""))
            for text, ids in _POINT_RE.findall(user.split("各部分要点：", 1)[-1])
        ]
        for i, (text, ids) in enumerate(found):
            if sections:
                sections[i % len(sections)]["points"].append({"text": text, "block_ids": ids})
        return "```json\n" + json.dumps({"sections": sections}, ensure_ascii=False) + "\n```"
    if '"points"' in messages[0].content and "[b_" in user:
        points = [
            {"text": text[:80], "block_ids": [bid]}
            for bid, text in _BLOCK_LINE_RE.findall(user)[:8]
        ]
        return json.dumps({"points": points}, ensure_ascii=False)
    return _echo(model, messages)


def qa_responder(model: str, messages: list[Message]) -> str:
    """看得懂 qa_answer 提示词的确定性回复（测试与 --fake 评测用）：引用上下文里的前两块，
    再故意带一个不存在的编号 b_9999，用来覆盖引用校验；末行是卡片标题。其他请求交给 summary_responder。"""
    user = messages[-1].content
    if "检索到的原文：" not in user:
        return summary_responder(model, messages)
    ids = [bid for bid, _ in _BLOCK_LINE_RE.findall(user)]
    if not ids:
        return "论文中没有找到相关内容。"
    first, second = ids[0], ids[min(1, len(ids) - 1)]
    question = user.rsplit("问题：", 1)[-1].strip()
    return (
        f"根据原文，第一点见此处 [{first}]。另外还有一点 [{second}][b_9999]。\n"
        f"标题：{question[:8]}要点"
    )


_ACRONYM_RE = re.compile(r"\b[A-Z][A-Za-z]*[A-Z][A-Za-z0-9-]*\b")
_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_KG_TYPES = ("Method", "Model", "Dataset", "Task", "Concept")


def kg_responder(model: str, messages: list[Message]) -> str:
    """看得懂 kg_extract 提示词的确定性回复（--fake 评测用）。

    每个块里的缩写词（两个以上大写字母）当作实体，类型按名称轮换；同一块里第一个缩写 uses
    其余的；有百分数时，第一个缩写 achieves 指标 "score"，数值取第一个百分数。
    """
    system, user = messages[0].content, messages[-1].content
    if '"entities"' not in system:
        return _echo(model, messages)
    entities: dict[str, dict] = {}
    relations = []
    for bid, text in _BLOCK_LINE_RE.findall(user):
        names = list(dict.fromkeys(_ACRONYM_RE.findall(text)))[:4]
        for n in names:
            etype = _KG_TYPES[sum(map(ord, n)) % len(_KG_TYPES)]
            entities.setdefault(n, {"id": n, "type": etype, "name": n, "block_ids": []})
            entities[n]["block_ids"].append(bid)
        relations += [
            {"src": names[0], "dst": n, "type": "uses", "block_id": bid} for n in names[1:]
        ]
        pct = _PERCENT_RE.search(text)
        if names and pct:
            entities.setdefault("score", {"id": "score", "type": "Metric", "name": "score"})
            relations.append(
                {
                    "src": names[0],
                    "dst": "score",
                    "type": "achieves",
                    "block_id": bid,
                    "attrs": {"metric": "score", "value": pct.group(1)},
                }
            )
    return json.dumps({"entities": list(entities.values()), "relations": relations})
