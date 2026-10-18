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


class Appearance(_Strict):
    theme_mode: Literal["system", "light", "dark"] = "system"
    # 种子色：预设（紫 #6750A4、蓝、青、绿、琥珀、玫红）或自定义；见 ADR-0006
    seed_color: str = "#6750A4"
    follow_system_accent: bool = False
    contrast: Literal["standard", "medium", "high"] = "standard"

    @field_validator("seed_color")
    @classmethod
    def _hex(cls, v: str) -> str:
        if not HEX_COLOR_RE.match(v):
            raise ValueError("seed_color must be #RRGGBB")
        return v.upper()


class ProviderConfig(_Strict):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,31}$")
    kind: Literal["openai_compatible", "anthropic", "ollama"] = "openai_compatible"
    name: str
    base_url: str


class ModelRoute(_Strict):
    provider_id: str
    model: str


class AppSettings(_Strict):
    appearance: Appearance = Appearance()
    target_lang: str = "zh-CN"
    # auto：先 PyMuPDF 快速模式，MinerU 可用时再升级（ADR-0003）
    parse_engine: Literal["auto", "pymupdf", "mineru", "docling"] = "auto"
    providers: list[ProviderConfig] = []
    routes: dict[TaskKind, ModelRoute] = {}
    # 用户已同意向其发送文档内容的 provider（architecture §10）
    consented_providers: list[str] = []

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
