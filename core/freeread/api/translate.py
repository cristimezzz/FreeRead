"""块级翻译（SSE）与已有译文。"""

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from freeread.api.deps import Ctx
from freeread.api.sse import encode, sse_response
from freeread.services.translate import TranslateError, TranslationOut

router = APIRouter(tags=["translate"])


class TranslateRequest(BaseModel):
    doc_id: str
    # 可视区域内的块，按希望的优先顺序排列
    block_ids: Annotated[list[str], Field(min_length=1, max_length=200)]
    lang: str | None = None  # 默认取设置中的目标语言


@router.post(
    "/translate/blocks",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def translate_blocks(ctx: Ctx, body: TranslateRequest, request: Request):
    """SSE 事件：
    - `translation`：TranslationEvent，每块一条；已有译文先发（cached=true），新译文按完成顺序；
    - `error`：`{code, message, provider_id?}`，整批无法进行，code 为 route_not_configured /
      missing_api_key / consent_required；已有译文仍会先发出；
    - `done`：结束。
    """
    try:
        await asyncio.to_thread(ctx.translate._load, body.doc_id)
    except LookupError as e:
        raise HTTPException(404 if "不存在" in str(e) else 409, str(e)) from e

    async def stream() -> AsyncIterator[str]:
        events = ctx.translate.translate_blocks(body.doc_id, body.block_ids, body.lang)
        try:
            async for event in events:
                if await request.is_disconnected():
                    break
                yield encode("translation", event.model_dump(mode="json", exclude_none=True))
        except TranslateError as e:
            yield encode("error", {"code": e.code, "message": str(e), "provider_id": e.provider_id})
        finally:
            await events.aclose()
        yield encode("done", {})

    return sse_response(stream())


@router.get("/documents/{doc_id}/translations", response_model=list[TranslationOut])
def list_translations(
    ctx: Ctx, doc_id: str, lang: Annotated[str | None, Query()] = None
) -> list[TranslationOut]:
    """该文档全部有效译文（只读本地库，离线可用）。"""
    if ctx.parse.get(doc_id) is None:
        raise HTTPException(404, "document not found")
    return ctx.translate.list_for_doc(doc_id, lang or ctx.settings.get().target_lang)
