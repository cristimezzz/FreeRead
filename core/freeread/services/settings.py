"""应用设置：schema、默认值与持久化（settings 表，每个顶层字段一行）。

API Key 不属于设置：它存在系统钥匙串，由 Rust 壳在启动 sidecar 时注入（architecture §5.4）。
"""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select

from freeread.infra.db.engine import SessionFactory
from freeread.infra.db.models import SettingRow
from freeread.infra.llm.gateway import TaskKind

HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


DEFAULT_ACCENT = "#D97757"
LEGACY_DEFAULT_SEED = "#6750A4"


class Appearance(_Strict):
    theme_mode: Literal["system", "light", "dark"] = "system"
    # 强调色（字段名沿用 M3 时期的 seed_color）：预设陶土 #D97757、墨蓝 #4F74B8、
    # 苔绿 #6F8546、石板 #6B6A63，或自定义；见 ADR-0007
    seed_color: str = DEFAULT_ACCENT
    follow_system_accent: bool = False
    contrast: Literal["standard", "medium", "high"] = "standard"

    @field_validator("seed_color")
    @classmethod
    def _hex(cls, v: str) -> str:
        if not HEX_COLOR_RE.match(v):
            raise ValueError("seed_color must be #RRGGBB")
        v = v.upper()
        # M3 时期的默认紫色不代表用户的选择，随新设计换成新默认
        return DEFAULT_ACCENT if v == LEGACY_DEFAULT_SEED else v


PARSER_KEY_PREFIX = "parser-"
DEFAULT_PROVIDER_CONCURRENCY = 4


class ProviderConfig(_Strict):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,31}$")
    kind: Literal["openai_compatible", "anthropic", "ollama"] = "openai_compatible"
    name: str
    base_url: str
    # 同时进行的请求数上限（所有任务共享）；服务商限流（429）时调小
    max_concurrency: int = Field(default=DEFAULT_PROVIDER_CONCURRENCY, ge=1, le=32)

    @field_validator("id")
    @classmethod
    def _not_reserved(cls, v: str) -> str:
        # parser-<engine> 是远程解析服务在钥匙串里的密钥 ID（ADR-0008）
        if v.startswith(PARSER_KEY_PREFIX):
            raise ValueError(f"provider id must not start with {PARSER_KEY_PREFIX!r}")
        return v


class RemoteParser(_Strict):
    """高质量引擎的运行位置（ADR-0008）。api：调用自部署或云端服务，而不是本机 .engines/。"""

    mode: Literal["local", "api"] = "local"
    base_url: str = Field(default="", pattern=r"^(https?://\S+)?$")
    # 仅 MinerU 使用；basic 与本机 effort=medium 同档
    tier: Literal["flash", "basic", "standard", "advanced"] = "basic"
    # 用户确认过可以上传 PDF 的公网地址；与 base_url 不同即视为未确认（局域网 / 本机地址无需确认）
    consented_url: str | None = None


class ParserServices(_Strict):
    mineru: RemoteParser = RemoteParser()
    docling: RemoteParser = RemoteParser()


class ModelRoute(_Strict):
    provider_id: str
    model: str


class EmbeddingSettings(_Strict):
    # local：内置本地模型（首次使用前要下载）；provider：走 routes["embed"] 指定的大模型服务
    source: Literal["local", "provider"] = "local"
    local_model: str = "multilingual-e5-small"
    # 解析完成后自动嵌入
    auto: bool = True
    # 模型下载源：Hugging Face 或兼容镜像（如 https://hf-mirror.com）
    mirror: str = Field(default="https://huggingface.co", pattern=r"^https?://\S+$")


class ZoteroSettings(_Strict):
    # auto：先连本地 API，Zotero 没运行时读 zotero.sqlite 快照
    source: Literal["auto", "local_api", "sqlite"] = "auto"
    # Zotero 数据目录（含 zotero.sqlite 和 storage/）；空表示默认的 ~/Zotero
    data_dir: str = ""


class GlossarySettings(_Strict):
    # 翻译全文前，文档还没有自动抽取的术语时先抽取一次（会多一次大模型调用）
    auto_extract: bool = False


class KGSettings(_Strict):
    # 嵌入完成后自动抽取知识图谱（每个章节组一次大模型调用）
    auto: bool = False


class AppSettings(_Strict):
    appearance: Appearance = Appearance()
    target_lang: str = "zh-CN"
    # auto：先 PyMuPDF 快速模式，MinerU 可用时再升级（ADR-0003）
    parse_engine: Literal["auto", "pymupdf", "mineru", "docling"] = "auto"
    parsers: ParserServices = ParserServices()
    # 本机 MinerU / Docling 的运行设备；auto 由引擎自行检测（有 CUDA 用 GPU），API 模式不受影响
    parse_device: Literal["auto", "gpu", "cpu"] = "auto"
    providers: list[ProviderConfig] = []
    routes: dict[TaskKind, ModelRoute] = {}
    # 用户已同意向其发送文档内容的 provider（architecture §10）
    consented_providers: list[str] = []
    embedding: EmbeddingSettings = EmbeddingSettings()
    glossary: GlossarySettings = GlossarySettings()
    kg: KGSettings = KGSettings()
    zotero: ZoteroSettings = ZoteroSettings()

    @model_validator(mode="after")
    def _check_refs(self) -> "AppSettings":
        ids = [p.id for p in self.providers]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate provider id")
        for task, route in self.routes.items():
            if route.provider_id not in ids:
                raise ValueError(f"route {task} refers to unknown provider {route.provider_id!r}")
        return self


class SettingsService:
    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    def get(self) -> AppSettings:
        with self._sessions() as s:
            stored = {r.key: r.value for r in s.scalars(select(SettingRow))}
        known = {k: v for k, v in stored.items() if k in AppSettings.model_fields}
        try:
            return AppSettings.model_validate(known)
        except ValueError:
            # 旧版本写入的值不再合法时逐个字段回退默认值，而不是让整个应用起不来。
            settings = AppSettings()
            for key, value in known.items():
                try:
                    settings = AppSettings.model_validate(
                        settings.model_dump(mode="json") | {key: value}
                    )
                except ValueError:
                    pass
            return settings

    def put(self, settings: AppSettings) -> AppSettings:
        # 隐私同意是针对"某个 provider 的某个地址"给的：服务被删除或换了 base_url，
        # 之前的同意作废，下次翻译前重新询问（否则改个地址就能把文档发到没确认过的服务）。
        previous = self.get()
        old_urls = {p.id: p.base_url for p in previous.providers}
        new_urls = {p.id: p.base_url for p in settings.providers}
        settings = settings.model_copy(
            update={
                "consented_providers": [
                    c
                    for c in settings.consented_providers
                    if c in new_urls
                    and (c not in previous.consented_providers or old_urls.get(c) == new_urls[c])
                ]
            }
        )
        data = settings.model_dump(mode="json")
        with self._sessions.begin() as s:
            for key, value in data.items():
                s.merge(SettingRow(key=key, value=value))
        return settings
