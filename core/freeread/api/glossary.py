"""术语表：增删改查与自动抽取。"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel

from freeread.api.deps import Ctx
from freeread.infra.jobs.queue import JobOut
from freeread.services.doc_blocks import DocumentNotReady
from freeread.services.glossary import GlossaryConflict, TermIn, TermOut, TermPatch
from freeread.services.llm_preflight import PreflightError

router = APIRouter(tags=["glossary"])


class ExtractRequest(BaseModel):
    lang: str | None = None  # 默认取设置中的目标语言


def preflight_http(e: PreflightError) -> HTTPException:
    """模型不可用：409，detail 为 {code, message, provider_id}，前端按 code 处理（如弹确认框）。"""
    return HTTPException(409, {"code": e.code, "message": str(e), "provider_id": e.provider_id})


@router.get("/glossary", response_model=list[TermOut])
def list_terms(
    ctx: Ctx,
    lang: Annotated[str | None, Query()] = None,
    doc_id: Annotated[str | None, Query()] = None,
) -> list[TermOut]:
    """不给 doc_id 只列全局条目；给了列全局 + 该文档条目（文档条目在前）。"""
    return ctx.glossary.list_terms(lang, doc_id)


@router.post("/glossary", response_model=TermOut, status_code=201)
def create_term(ctx: Ctx, body: TermIn) -> TermOut:
    if body.doc_id and ctx.parse.get(body.doc_id) is None:
        raise HTTPException(404, "document not found")
    try:
        return ctx.glossary.create(body)
    except GlossaryConflict as e:
        raise HTTPException(409, str(e)) from e


@router.patch("/glossary/{term_id}", response_model=TermOut)
def update_term(ctx: Ctx, term_id: str, body: TermPatch) -> TermOut:
    try:
        return ctx.glossary.update(term_id, body)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except GlossaryConflict as e:
        raise HTTPException(409, str(e)) from e


@router.delete("/glossary/{term_id}", status_code=204)
def delete_term(ctx: Ctx, term_id: str) -> Response:
    if not ctx.glossary.delete(term_id):
        raise HTTPException(404, "term not found")
    return Response(status_code=204)


@router.post("/documents/{doc_id}/glossary/extract", response_model=JobOut, status_code=202)
def extract_terms(ctx: Ctx, doc_id: str, body: ExtractRequest | None = None) -> JobOut:
    """排队自动抽取（已有同一文档、同一语言的任务时返回它）。重新抽取只替换自动条目。"""
    try:
        return ctx.glossary.request_extract(doc_id, (body or ExtractRequest()).lang)
    except DocumentNotReady as e:
        raise HTTPException(409, str(e)) from e
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except PreflightError as e:
        raise preflight_http(e) from e
