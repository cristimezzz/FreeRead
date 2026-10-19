"""远程解析服务（MinerU / docling-serve 的 API 模式）的密钥与连通性测试。见 ADR-0008。

密钥同 LLM provider：前端调 Tauri 命令 `set_api_key`（ID 为 parser-<engine>）写系统钥匙串后，
再调 `PUT /parsers/{engine}/key` 让运行中的 Core 生效。任何响应都不返回密钥本身。
"""

import time
from typing import Literal

import httpx
from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, Field

from freeread.api.deps import Ctx
from freeread.api.llm import KeyIn
from freeread.infra.parsers.docling_api import DoclingServeParser
from freeread.infra.parsers.mineru_api import MinerUApiParser
from freeread.infra.parsers.remote_common import RemoteParseError
from freeread.services.settings import PARSER_KEY_PREFIX

router = APIRouter(prefix="/parsers", tags=["parsers"])

RemoteEngine = Literal["mineru", "docling"]


class ParserTestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # 省略时用设置里保存的地址（便于保存前先测试）
    base_url: str | None = Field(default=None, pattern=r"^https?://\S+$")


class ParserTestOut(BaseModel):
    ok: bool
    latency_ms: int
    version: str | None = None
    error: str | None = None


@router.put("/{engine}/key", status_code=204, response_class=Response)
def put_key(ctx: Ctx, engine: RemoteEngine, body: KeyIn) -> Response:
    ctx.secrets.set(PARSER_KEY_PREFIX + engine, body.key.strip())
    return Response(status_code=204)


@router.delete("/{engine}/key", status_code=204, response_class=Response)
def delete_key(ctx: Ctx, engine: RemoteEngine) -> Response:
    ctx.secrets.delete(PARSER_KEY_PREFIX + engine)
    return Response(status_code=204)


@router.post("/{engine}/test", response_model=ParserTestOut)
async def test_service(
    ctx: Ctx, engine: RemoteEngine, body: ParserTestIn | None = None
) -> ParserTestOut:
    """只请求健康检查等接口，不上传任何文档。配置错误也以 ok=false 返回，而不是 4xx。"""
    cfg = getattr(ctx.settings.get().parsers, engine)
    base_url = (body.base_url if body and body.base_url else None) or cfg.base_url
    started = time.perf_counter()
    version = error = None
    if not base_url:
        error = "未填写服务地址"
    else:
        key = ctx.secrets.get(PARSER_KEY_PREFIX + engine)
        parser = (
            MinerUApiParser(base_url, key, cfg.tier)
            if engine == "mineru"
            else DoclingServeParser(base_url, key)
        )
        try:
            version = await parser.check()
        except RemoteParseError as exc:
            error = ctx.secrets.redact(str(exc))
        except (httpx.HTTPError, httpx.InvalidURL, ValueError) as exc:
            error = ctx.secrets.redact(f"{type(exc).__name__}: {exc}")
    return ParserTestOut(
        ok=error is None,
        latency_ms=int((time.perf_counter() - started) * 1000),
        version=version,
        error=error,
    )
