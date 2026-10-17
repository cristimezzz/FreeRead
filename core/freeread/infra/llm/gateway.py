"""LLM Gateway 接口。见 docs/adr/0005-llm-gateway.md 与 docs/01-architecture.md §5.4。"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class TaskKind(StrEnum):
    TRANSLATE = "translate"
    SUMMARIZE = "summarize"
    QA = "qa"
    KG_EXTRACT = "kg_extract"
    GLOSSARY = "glossary"
    EMBED = "embed"


@dataclass
class Message:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class Usage:
    input_tokens: int
    output_tokens: int


@dataclass
class LLMResult:
    text: str
    model: str
    usage: Usage
    cache_hit: bool = False


@dataclass
class LLMChunk:
    delta: str
    done: bool = False
    usage: Usage | None = None


class Provider(Protocol):
    """单个提供方的适配器：openai_compatible / anthropic / ollama。"""

    name: str

    async def complete(self, model: str, messages: list[Message], **opts) -> LLMResult: ...

    def stream(self, model: str, messages: list[Message], **opts) -> AsyncIterator[LLMChunk]: ...

    async def embed(self, model: str, texts: list[str]) -> list[list[float]]: ...


class LLMGateway(Protocol):
    """按 TaskKind 路由到配置的 provider/model，并统一处理缓存、限流、重试与用量审计。"""

    async def complete(
        self, task: TaskKind, messages: list[Message], *, prompt_id: str, **opts
    ) -> LLMResult: ...

    def stream(
        self, task: TaskKind, messages: list[Message], *, prompt_id: str, **opts
    ) -> AsyncIterator[LLMChunk]: ...

    async def embed(self, texts: list[str]) -> list[list[float]]: ...
