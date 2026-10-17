"""解析引擎接口。见 docs/adr/0003-pluggable-parser.md 与 docs/01-architecture.md §5.2。"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from freeread.domain.ir.models import Document

ProgressCb = Callable[[float, str], None]


@dataclass(frozen=True)
class ParserCaps:
    formulas: bool
    tables: bool
    ocr: bool
    needs_gpu: bool


@dataclass
class RawLayout:
    """引擎原生输出，原样保存在 documents/<doc_id>/raw/，便于重新规范化。"""

    engine: str
    engine_version: str
    raw_dir: Path
    data: Any


class Parser(Protocol):
    name: str
    version: str

    def capabilities(self) -> ParserCaps: ...

    async def parse(self, pdf: Path, out_dir: Path, progress: ProgressCb) -> RawLayout: ...


class Normalizer(Protocol):
    """把某个引擎的 RawLayout 转换为 Document IR。每个引擎一个实现。"""

    engine: str
    version: str

    def normalize(self, raw: RawLayout, pdf_sha256: str) -> Document: ...
