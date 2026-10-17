"""LLM provider 的密钥与连通性测试。

密钥只存内存（SecretStore），持久化由 Rust 壳的系统钥匙串负责：
前端调 Tauri 命令 `set_api_key` 写钥匙串后，再调 `PUT /llm/providers/{id}/key` 让运行中的 Core 生效。
任何响应都不返回密钥本身。
"""

import time
from typing import Annotated

import httpx
from fastapi import APIRouter, HTTPException, Path, Response
from pydantic import BaseModel, ConfigDict, Field

from freeread.api.deps import Ctx
from freeread.infra.llm.errors import LLMError

router = APIRouter(prefix="/llm", tags=["llm"])

ProviderId = Annotated[str, Path(pattern=r"^[a-z0-9][a-z0-9_-]{0,31}$")]


class ProviderStatus(BaseModel):
    id: str
    name: str
    kind: str
    has_key: bool


class KeyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=4096, repr=False)


class TestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # 省略时用路由到该 provider 的第一个模型
    model: str | None = None


class TestOut(BaseModel):
    ok: bool
    model: str | None
    latency_ms: int
    error: str | None = None


@router.get("/providers", response_model=list[ProviderStatus])
def list_providers(ctx: Ctx) -> list[ProviderStatus]:
    """设置里的 provider 及是否已有密钥（不含密钥本身）。"""
    return [
        ProviderStatus(id=p.id, name=p.name, kind=p.kind, has_key=ctx.secrets.has(p.id))
        for p in ctx.settings.get().providers
    ]


@router.put("/providers/{provider_id}/key", status_code=204, response_class=Response)
def put_key(ctx: Ctx, provider_id: ProviderId, body: KeyIn) -> Response:
    ctx.secrets.set(provider_id, body.key.strip())
    return Response(status_code=204)


@router.delete("/providers/{provider_id}/key", status_code=204, response_class=Response)
def delete_key(ctx: Ctx, provider_id: ProviderId) -> Response:
    ctx.secrets.delete(provider_id)
    return Response(status_code=204)


@router.post("/providers/{provider_id}/test", response_model=TestOut)
async def test_provider(ctx: Ctx, provider_id: ProviderId, body: TestIn | None = None) -> TestOut:
    """发一条极短的请求验证 base_url、密钥与模型。配置错误也以 ok=false 返回，而不是 4xx。"""
    settings = ctx.settings.get()
    if not any(p.id == provider_id for p in settings.providers):
        raise HTTPException(404, "provider not configured")
    model = body.model if body and body.model else None
    if model is None:
        model = next(
            (r.model for r in settings.routes.values() if r.provider_id == provider_id), None
        )
    if model is None:
        raise HTTPException(422, "no model given and no task is routed to this provider")

    started = time.perf_counter()
    try:
        await ctx.llm.test_provider(provider_id, model)
        error = None
    except LLMError as exc:
        error = ctx.secrets.redact(str(exc))
    except (httpx.HTTPError, httpx.InvalidURL) as exc:  # base_url 写错等也作为结果返回
        error = ctx.secrets.redact(f"{type(exc).__name__}: {exc}")
    return TestOut(
        ok=error is None,
        model=model,
        latency_ms=int((time.perf_counter() - started) * 1000),
        error=error,
    )
