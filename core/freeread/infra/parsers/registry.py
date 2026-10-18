"""已知解析引擎及其可用性。见 ADR-0003。

- pymupdf：快速模式，随 sidecar 分发，总是可用；
- mineru：默认高质量引擎，常驻 worker（进程在本注册表内共享）；
- docling：备选高质量引擎，每篇起一个子进程。
重型引擎在 M1 只在开发环境可用：需要 .engines/<engine>/ 下的独立 Python 环境
（或环境变量 FREEREAD_<ENGINE>_PYTHON），首次使用时下载在 M2 实现。
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from freeread.infra.parsers.base import Normalizer, Parser
from freeread.infra.parsers.subprocess_engine import engine_python


@dataclass
class EngineSpec:
    name: str
    label: str
    rank: int  # 质量等级：自动流程不会用低等级结果覆盖高等级结果
    make_parser: Callable[[], Parser]
    normalizer: Normalizer
    available: Callable[[], bool]
    heavy: bool  # 重型引擎走 parse_hq 任务（全局并发 1）


class ParserRegistry:
    def __init__(self, log_dir: Path | None = None) -> None:
        from freeread.infra.parsers.docling import DoclingNormalizer, docling_parser
        from freeread.infra.parsers.mineru import MinerUNormalizer
        from freeread.infra.parsers.pymupdf_fast import PyMuPDFFastNormalizer, PyMuPDFFastParser
        from freeread.infra.parsers.resident import mineru_resident

        self._mineru = None

        def mineru() -> Parser:
            if self._mineru is None:
                self._mineru = mineru_resident(log_dir)
            return self._mineru

        def has_env(engine: str) -> Callable[[], bool]:
            return lambda: engine_python(engine).is_file()

        self.engines: dict[str, EngineSpec] = {
            "pymupdf": EngineSpec(
                "pymupdf",
                "快速模式（PyMuPDF）",
                0,
                PyMuPDFFastParser,
                PyMuPDFFastNormalizer(),
                lambda: True,
                heavy=False,
            ),
            "docling": EngineSpec(
                "docling",
                "Docling",
                1,
                docling_parser,
                DoclingNormalizer(),
                has_env("docling"),
                heavy=True,
            ),
            "mineru": EngineSpec(
                "mineru",
                "MinerU",
                2,
                mineru,
                MinerUNormalizer(),
                has_env("mineru"),
                heavy=True,
            ),
        }

    def get(self, name: str) -> EngineSpec:
        try:
            return self.engines[name]
        except KeyError:
            raise ValueError(f"unknown parser engine {name!r}") from None

    async def close(self) -> None:
        if self._mineru is not None:
            await self._mineru.close()
