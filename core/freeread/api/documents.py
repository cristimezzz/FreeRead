"""文档：解析状态、IR、原始 PDF、图表图片、（重新）解析。"""

import math
import re

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from freeread.api.deps import Ctx
from freeread.infra.jobs.queue import JobOut
from freeread.services.parse import (
    ASSET_DPI,
    DocumentOut,
    EngineOut,
    EngineUnavailableError,
    ReparseAllOut,
)

router = APIRouter(tags=["documents"])

ASSET_NAME_RE = re.compile(r"^a_\d{4,}\.png$")
# IR 与图表图片在重新解析后原地替换（同一 URL、同名 a_0000.png）。不带 Cache-Control 时
# WebView 会按 Last-Modified 启发式缓存（旧文件越旧缓存越久），升级后仍显示快速模式的结果；
# no-cache 要求每次向本机 Core 重新验证。
REVALIDATE = {"Cache-Control": "no-cache"}


class ParseRequest(BaseModel):
    # 为空时走默认链：快速模式，再按设置用高质量引擎升级
    engine: str | None = None


class ReparseAllRequest(BaseModel):
    engine: str


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
    return FileResponse(path, media_type="application/json", headers=REVALIDATE)


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
    "/documents/{doc_id}/figure-crop",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
def get_figure_crop(ctx: Ctx, doc_id: str, page: int, x0: float, y0: float, x1: float, y1: float):
    """Clip a figure from the original PDF for reflow, using zero-based pages and PDF points."""
    import pymupdf

    _doc_or_404(ctx, doc_id)
    if not all(map(math.isfinite, (x0, y0, x1, y1))) or x0 >= x1 or y0 >= y1:
        raise HTTPException(422, "invalid crop bounds")
    path = ctx.parse.pdf_path(doc_id)
    if path is None:
        raise HTTPException(404, "pdf file missing")
    try:
        with pymupdf.open(path) as pdf:
            if not 0 <= page < pdf.page_count:
                raise HTTPException(404, "pdf page not found")
            pdf_page = pdf[page]
            bounds = pdf_page.rect
            left, top = max(x0, bounds.x0), max(y0, bounds.y0)
            right, bottom = min(x1, bounds.x1), min(y1, bounds.y1)
            if left >= right or top >= bottom:
                raise HTTPException(422, "crop outside page")
            rect = pymupdf.Rect(left, top, right, bottom)
            pixels = (rect * pymupdf.Matrix(ASSET_DPI / 72, ASSET_DPI / 72)).irect
            if pixels.width * pixels.height > 16_000_000:
                raise HTTPException(422, "crop too large")
            png = pdf_page.get_pixmap(clip=rect, dpi=ASSET_DPI).tobytes("png")
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(422, "pdf crop unavailable") from exc
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.get(
    "/documents/{doc_id}/assets/{name}",
    response_class=FileResponse,
    responses={200: {"content": {"image/png": {}}}},
)
def get_asset(ctx: Ctx, doc_id: str, name: str):
    _doc_or_404(ctx, doc_id)  # doc_id 要先确认存在，否则 ".." 之类的值会拼出数据目录之外的路径
    if not ASSET_NAME_RE.match(name):
        raise HTTPException(404, "asset not found")
    path = ctx.parse.asset_path(doc_id, name)
    if not path.is_file():
        raise HTTPException(404, "asset not found")
    return FileResponse(path, media_type="image/png", headers=REVALIDATE)


@router.post("/documents/{doc_id}/parse", response_model=JobOut, status_code=202)
def parse_document(ctx: Ctx, doc_id: str, body: ParseRequest | None = None) -> JobOut:
    _doc_or_404(ctx, doc_id)
    try:
        return ctx.parse.request_parse(doc_id, body.engine if body else None)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except EngineUnavailableError as e:
        raise HTTPException(409, str(e)) from e


@router.post("/documents/reparse-all", response_model=ReparseAllOut, status_code=202)
def reparse_all_documents(ctx: Ctx, body: ReparseAllRequest) -> ReparseAllOut:
    try:
        return ctx.parse.request_reparse_all(body.engine)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except EngineUnavailableError as e:
        raise HTTPException(409, str(e)) from e
