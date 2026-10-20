"""高亮与批注；导出 Markdown。"""

import asyncio
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel

from freeread.api.deps import Ctx
from freeread.services.annotations import (
    AnnotationError,
    AnnotationIn,
    AnnotationOut,
    AnnotationPatch,
)
from freeread.services.doc_blocks import DocumentNotReady
from freeread.services.export import ExportOptions

router = APIRouter(tags=["annotations"])


def _doc_or_404(ctx, doc_id: str) -> None:
    if ctx.parse.get(doc_id) is None:
        raise HTTPException(404, "document not found")


@router.get("/documents/{doc_id}/annotations", response_model=list[AnnotationOut])
def list_annotations(ctx: Ctx, doc_id: str) -> list[AnnotationOut]:
    """按阅读顺序排列（只读本地库）。"""
    _doc_or_404(ctx, doc_id)
    return ctx.annotations.list_for_doc(doc_id)


@router.post("/documents/{doc_id}/annotations", response_model=AnnotationOut, status_code=201)
def create_annotation(ctx: Ctx, doc_id: str, body: AnnotationIn) -> AnnotationOut:
    try:
        return ctx.annotations.create(doc_id, body)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except AnnotationError as e:
        raise HTTPException(422, str(e)) from e


@router.patch("/annotations/{annotation_id}", response_model=AnnotationOut)
def update_annotation(ctx: Ctx, annotation_id: str, body: AnnotationPatch) -> AnnotationOut:
    try:
        return ctx.annotations.update(annotation_id, body)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e


@router.delete("/annotations/{annotation_id}", status_code=204)
def delete_annotation(ctx: Ctx, annotation_id: str) -> Response:
    if not ctx.annotations.delete(annotation_id):
        raise HTTPException(404, "annotation not found")
    return Response(status_code=204)


# ------------------------------------------------------------ 导出


def _export(ctx, doc_id: str, opts: ExportOptions) -> str:
    try:
        return ctx.export.markdown(doc_id, opts)
    except DocumentNotReady as e:
        raise HTTPException(409, str(e)) from e
    except LookupError as e:
        raise HTTPException(404, str(e)) from e


@router.get(
    "/documents/{doc_id}/export/markdown",
    response_class=Response,
    responses={200: {"content": {"text/markdown": {}}}},
)
async def export_markdown(
    ctx: Ctx, doc_id: str, opts: Annotated[ExportOptions, Query()]
) -> Response:
    """导出为 Markdown 文本（浏览器模式下载用）。"""
    text = await asyncio.to_thread(_export, ctx, doc_id, opts)
    return Response(text, media_type="text/markdown; charset=utf-8")


class ExportToFile(ExportOptions):
    path: str  # 本机绝对路径（桌面版由保存对话框选出）


class ExportResult(BaseModel):
    path: str
    bytes: int


@router.post("/documents/{doc_id}/export/markdown", response_model=ExportResult)
async def export_markdown_to_file(ctx: Ctx, doc_id: str, body: ExportToFile) -> ExportResult:
    """导出并写入本机文件（桌面版）。"""
    path = Path(body.path)
    if not path.is_absolute() or not path.parent.is_dir():
        raise HTTPException(422, "路径必须是已存在目录下的绝对路径")
    text = await asyncio.to_thread(_export, ctx, doc_id, body)
    data = text.encode("utf-8")
    try:
        await asyncio.to_thread(path.write_bytes, data)
    except OSError as e:
        raise HTTPException(422, f"无法写入文件：{e}") from e
    return ExportResult(path=str(path), bytes=len(data))
