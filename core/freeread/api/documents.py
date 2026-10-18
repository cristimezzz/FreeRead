"""文档：解析状态、IR、原始 PDF、图表图片、（重新）解析。"""

import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from freeread.api.deps import Ctx
from freeread.infra.jobs.queue import JobOut
from freeread.services.parse import DocumentOut, EngineOut, EngineUnavailableError

router = APIRouter(tags=["documents"])

ASSET_NAME_RE = re.compile(r"^a_\d{4,}\.png$")


class ParseRequest(BaseModel):
    # 为空时走默认链：快速模式，再按设置用高质量引擎升级
    engine: str | None = None


def _doc_or_404(ctx, doc_id: str) -> DocumentOut:
    doc = ctx.parse.get(doc_id)
    if doc is None:
        raise HTTPException(404, "document not found")
    return doc


@router.get("/parsers", response_model=list[EngineOut])
def list_parsers(ctx: Ctx) -> list[EngineOut]:
    return ctx.parse.engines()


@router.get("/documents/{doc_id}", response_model=DocumentOut)
def get_document(ctx: Ctx, doc_id: str) -> DocumentOut:
    return _doc_or_404(ctx, doc_id)


@router.get(
    "/documents/{doc_id}/ir",
    response_class=FileResponse,
    responses={200: {"content": {"application/json": {}}, "description": "Document IR 0.x"}},
)
def get_ir(ctx: Ctx, doc_id: str):
    """IR 全文（docs/schemas/ir-0.1.0.json）。尚未解析完成时返回 409。"""
    doc = _doc_or_404(ctx, doc_id)
    path = ctx.parse.ir_path(doc_id)
    if not path.is_file():
        raise HTTPException(409, f"document not parsed yet ({doc.parse_status})")
    return FileResponse(path, media_type="application/json")


@router.get(
    "/documents/{doc_id}/pdf",
    response_class=FileResponse,
    responses={200: {"content": {"application/pdf": {}}}},
)
def get_pdf(ctx: Ctx, doc_id: str):
    _doc_or_404(ctx, doc_id)
    path = ctx.parse.pdf_path(doc_id)
    if path is None:
        raise HTTPException(404, "pdf file missing")
    return FileResponse(path, media_type="application/pdf")


@router.get(
    "/documents/{doc_id}/assets/{name}",
    response_class=FileResponse,
    responses={200: {"content": {"image/png": {}}}},
)
def get_asset(ctx: Ctx, doc_id: str, name: str):
    if not ASSET_NAME_RE.match(name):
        raise HTTPException(404, "asset not found")
    path = ctx.parse.asset_path(doc_id, name)
    if not path.is_file():
        raise HTTPException(404, "asset not found")
    return FileResponse(path, media_type="image/png")


@router.post("/documents/{doc_id}/parse", response_model=JobOut, status_code=202)
def parse_document(ctx: Ctx, doc_id: str, body: ParseRequest | None = None) -> JobOut:
    _doc_or_404(ctx, doc_id)
    try:
        return ctx.parse.request_parse(doc_id, body.engine if body else None)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except EngineUnavailableError as e:
        raise HTTPException(409, str(e)) from e
