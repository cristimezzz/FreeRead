"""已知解析引擎及其可用性。见 ADR-0003、ADR-0008。

- pymupdf：快速模式，随 sidecar 分发，总是可用；
- mineru：默认高质量引擎，本机按需复用多个常驻 worker；
- docling：备选高质量引擎，本机每篇起一个子进程。
重型引擎的本机模式需要 <engines_root>/<engine>/ 下的独立 Python 环境（或环境变量
FREEREAD_<ENGINE>_PYTHON）：开发时为仓库下的 .engines/，打包版由设置里的"安装"创建（installer.py）。
mineru / docling 也可以设为 API 模式（settings.parsers），改为调用自部署或云端服务；
引擎名、Normalizer、raw/<engine>/ 与质量等级都不变。设置每次调用时读取，改了立即生效。
"""

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from freeread.infra.parsers.base import Normalizer, Parser
from freeread.infra.parsers.remote_common import is_local_url
from freeread.infra.parsers.subprocess_engine import engine_python

if TYPE_CHECKING:
    from freeread.services.settings import RemoteParser

# 不可用的原因：not_installed（本机未安装）/ not_configured（API 模式未填地址）/
# consent_required（公网地址，用户还没确认上传）
UnavailableReason = Literal["not_installed", "not_configured", "consent_required"]


@dataclass
class EngineSpec:
    name: str
    label: str
    rank: int  # 质量等级：自动流程不会用低等级结果覆盖高等级结果
    make_parser: Callable[[], Parser]
    normalizer: Normalizer
    available: Callable[[], bool]
    heavy: bool  # 重型引擎走 parse_hq 任务
    location: Callable[[], Literal["local", "api"]] = field(default=lambda: "local")
    unavailable_reason: Callable[[], UnavailableReason | None] = field(default=lambda: None)
    snapshot: "Callable[[], EngineSpec] | None" = None


class ParserRegistry:
    def __init__(
        self,
        log_dir: Path | None = None,
        remote: "Callable[[str], RemoteParser | None] | None" = None,
        secret: Callable[[str], str | None] | None = None,
        device: Callable[[], str] | None = None,
    ) -> None:
        """remote(engine)：该引擎处于 API 模式时返回其配置，否则 None；secret(engine)：API Key；
        device()：本机引擎的运行设备（auto / gpu / cpu）。"""
        from freeread.infra.parsers.docling import DoclingNormalizer, docling_parser
        from freeread.infra.parsers.docling_api import DoclingServeParser
        from freeread.infra.parsers.mineru import MinerUNormalizer
        from freeread.infra.parsers.mineru_api import MinerUApiParser
        from freeread.infra.parsers.pymupdf_fast import PyMuPDFFastNormalizer, PyMuPDFFastParser
        from freeread.infra.parsers.resident import ResidentParserPool, mineru_resident

        self._mineru: ResidentParserPool | None = None
        remote_of = remote or (lambda engine: None)
        secret_of = secret or (lambda engine: None)

        def mineru_local() -> Parser:
            if self._mineru is None:
                self._mineru = ResidentParserPool(lambda: mineru_resident(log_dir, device))
            return self._mineru

        def api_parser(engine: str, cfg: "RemoteParser") -> Parser:
            key = secret_of(engine)
            if engine == "mineru":
                return MinerUApiParser(cfg.base_url, key, cfg.tier)
            return DoclingServeParser(cfg.base_url, key)

        def heavy(engine: str, label: str, rank: int, local: Callable[[], Parser], normalizer):
            def reason(cfg: "RemoteParser | None") -> UnavailableReason | None:
                if cfg is None:
                    return None if engine_python(engine).is_file() else "not_installed"
                if not cfg.base_url:
                    return "not_configured"
                if not is_local_url(cfg.base_url) and cfg.consented_url != cfg.base_url:
                    return "consent_required"
                return None

            def make(cfg: "RemoteParser | None") -> Parser:
                return local() if cfg is None else api_parser(engine, cfg)

            def snapshot() -> EngineSpec:
                # 同一次解析用同一份配置判断运行位置、上传同意和服务地址。
                cfg = remote_of(engine)
                unavailable = reason(cfg)
                return replace(
                    spec,
                    make_parser=lambda: make(cfg),
                    available=lambda: unavailable is None,
                    location=lambda: "local" if cfg is None else "api",
                    unavailable_reason=lambda: unavailable,
                    snapshot=None,
                )

            spec = EngineSpec(
                engine,
                label,
                rank,
                lambda: make(remote_of(engine)),
                normalizer,
                lambda: reason(remote_of(engine)) is None,
                heavy=True,
                location=lambda: "local" if remote_of(engine) is None else "api",
                unavailable_reason=lambda: reason(remote_of(engine)),
                snapshot=snapshot,
            )
            return spec

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
            "docling": heavy(
                "docling", "Docling", 1, lambda: docling_parser(device), DoclingNormalizer()
            ),
            "mineru": heavy("mineru", "MinerU", 2, mineru_local, MinerUNormalizer()),
        }

    def get(self, name: str) -> EngineSpec:
        try:
            return self.engines[name]
        except KeyError:
            raise ValueError(f"unknown parser engine {name!r}") from None

    async def close(self) -> None:
        if self._mineru is not None:
            await self._mineru.close()
