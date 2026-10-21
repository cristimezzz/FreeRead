"""单篇论文问答：对话与节点的增删查，在问答树的某个节点下提问（SSE）。"""

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from freeread.api.deps import Ctx
from freeread.api.sse import encode, sse_response
from freeread.infra.llm.errors import LLMError
from freeread.services.doc_blocks import DocumentNotReady
from freeread.services.llm_preflight import PreflightError
from freeread.services.qa import QASessionDetail, QASessionOut

router = APIRouter(tags=["qa"])


class NewSession(BaseModel):
    title: str = ""


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    lang: str | None = None  # 默认取设置中的目标语言
    # 挂在哪个节点下；None 为对话里新的根（新话题）
    parent_id: str | None = None
    # 就此追问：父节点回答里选中的文字
    anchor: str | None = Field(default=None, max_length=500)
    # 重答同一问题（作为兄弟节点）：不使用缓存
    regenerate: bool = False


def _doc_or_404(ctx, doc_id: str) -> None:
    if ctx.parse.get(doc_id) is None:
        raise HTTPException(404, "document not found")


@router.get("/documents/{doc_id}/qa/sessions", response_model=list[QASessionOut])
def list_sessions(ctx: Ctx, doc_id: str) -> list[QASessionOut]:
    """该文档的对话，最近活动的在前（只读本地库，离线可用）。"""
    _doc_or_404(ctx, doc_id)
    return ctx.qa.list_sessions(doc_id)


@router.post("/documents/{doc_id}/qa/sessions", response_model=QASessionOut, status_code=201)
def create_session(ctx: Ctx, doc_id: str, body: NewSession | None = None) -> QASessionOut:
    _doc_or_404(ctx, doc_id)
    return ctx.qa.create_session(doc_id, (body or NewSession()).title)


@router.get("/qa/sessions/{session_id}", response_model=QASessionDetail)
def get_session(ctx: Ctx, session_id: str) -> QASessionDetail:
    try:
        return ctx.qa.get_session(session_id)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e


@router.delete("/qa/sessions/{session_id}", status_code=204)
def delete_session(ctx: Ctx, session_id: str) -> Response:
    if not ctx.qa.delete_session(session_id):
        raise HTTPException(404, "session not found")
    return Response(status_code=204)


@router.delete("/qa/nodes/{node_id}", status_code=204)
def delete_node(ctx: Ctx, node_id: str) -> Response:
    """删除节点及其整棵子树。"""
    if not ctx.qa.delete_node(node_id):
        raise HTTPException(404, "node not found")
    return Response(status_code=204)


@router.post(
    "/qa/sessions/{session_id}/ask",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def ask(ctx: Ctx, session_id: str, body: AskRequest, request: Request):
    """SSE 事件：
    - `context`：QAContextOut，送给模型的原文块与检索方式（没有 vector 表示语义索引未建）；
    - `delta`：`{text}`，流式输出的原始文本（引用尚未校验，前端只用来即时显示）；
    - `answer`：QANodeOut，校验并保存后的这一轮（以它为准替换流式文本）；
    - `error`：`{code, message, provider_id?}`，code 为 route_not_configured / missing_api_key /
      consent_required / bad_request（parent_id 不在该对话）/ no_text / bad_output / llm_error；
    - `done`：结束。
    """
    try:
        session = await asyncio.to_thread(ctx.qa.get_session, session_id)
        await asyncio.to_thread(ctx.qa.load, session.doc_id)
    except DocumentNotReady as e:
        raise HTTPException(409, str(e)) from e
    except LookupError as e:
        raise HTTPException(404, str(e)) from e

    async def stream() -> AsyncIterator[str]:
        events = ctx.qa.ask(
            session_id,
            body.question,
            body.lang,
            parent_id=body.parent_id,
            anchor=body.anchor,
            regenerate=body.regenerate,
        )
        try:
            async for name, payload in events:
                if await request.is_disconnected():
                    break
                yield encode(name, payload.model_dump(mode="json"))
        except PreflightError as e:  # 含 QAError
            yield encode("error", {"code": e.code, "message": str(e), "provider_id": e.provider_id})
        except LLMError as e:
            yield encode("error", {"code": "llm_error", "message": str(e), "provider_id": None})
        finally:
            await events.aclose()
        yield encode("done", {})

    return sse_response(stream())
