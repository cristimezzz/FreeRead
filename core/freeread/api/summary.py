"""分层总结：模板、已有总结、生成（SSE）。"""

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from freeread.api.deps import Ctx
from freeread.api.sse import encode, sse_response
from freeread.infra.llm.errors import LLMError
from freeread.services.doc_blocks import DocumentNotReady
from freeread.services.llm_preflight import PreflightError
from freeread.services.summary import SummaryOut, TemplateOut

router = APIRouter(tags=["summary"])


class SummaryRequest(BaseModel):
    template_id: str = "paper"
    lang: str | None = None  # 默认取设置中的目标语言


@router.get("/summary/templates", response_model=list[TemplateOut])
def list_templates(ctx: Ctx) -> list[TemplateOut]:
    return ctx.summary.templates()


@router.get("/documents/{doc_id}/summaries", response_model=list[SummaryOut])
def list_summaries(
    ctx: Ctx, doc_id: str, lang: Annotated[str | None, Query()] = None
) -> list[SummaryOut]:
    """该文档已有的总结（只读本地库，离线可用），新的在前。"""
    if ctx.parse.get(doc_id) is None:
        raise HTTPException(404, "document not found")
    return ctx.summary.list_for_doc(doc_id, lang or ctx.settings.get().target_lang)


@router.post(
    "/documents/{doc_id}/summary",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def generate_summary(ctx: Ctx, doc_id: str, body: SummaryRequest, request: Request):
    """SSE 事件：
    - `progress`：SummaryProgress，Map 阶段每完成一组一条，Reduce 开始时一条；
    - `summary`：SummaryOut，生成并保存后的结果；
    - `error`：`{code, message, provider_id?}`，code 为 route_not_configured / missing_api_key /
      consent_required / unknown_template / llm_error / bad_output；
    - `done`：结束。
    """
    try:
        await asyncio.to_thread(ctx.summary.load, doc_id)
    except DocumentNotReady as e:
        raise HTTPException(409, str(e)) from e
    except LookupError as e:
        raise HTTPException(404, str(e)) from e

    async def stream() -> AsyncIterator[str]:
        events = ctx.summary.generate(doc_id, body.template_id, body.lang)
        try:
            async for name, payload in events:
                if await request.is_disconnected():
                    break
                yield encode(name, payload.model_dump(mode="json"))
        except PreflightError as e:  # 含 SummaryError
            yield encode("error", {"code": e.code, "message": str(e), "provider_id": e.provider_id})
        except LLMError as e:
            yield encode("error", {"code": "llm_error", "message": str(e), "provider_id": None})
        finally:
            await events.aclose()
        yield encode("done", {})

    return sse_response(stream())
