"""文献库：分类、条目、Zotero 同步、手动导入。"""

from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from freeread.api.deps import Ctx
from freeread.infra.jobs.queue import JobOut
from freeread.services.library import (
    CollectionOut,
    InvalidImportError,
    ItemDetail,
    ItemPage,
    ItemSort,
)

router = APIRouter(prefix="/library", tags=["library"])


class SyncRequest(BaseModel):
    # Zotero 分类 key；给定时只为该分类（含子分类）下的条目建解析任务
    collection_key: str | None = None


class ImportFileRequest(BaseModel):
    path: str  # 本地绝对路径，由 Tauri 文件对话框取得


class ImportFileResult(BaseModel):
    item: ItemDetail
    created: bool


@router.get("/collections", response_model=list[CollectionOut])
def list_collections(ctx: Ctx) -> list[CollectionOut]:
    return ctx.library.list_collections()


@router.get("/items", response_model=ItemPage)
def list_items(
    ctx: Ctx,
    collection_id: str | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    status: Literal["active", "archived"] = "active",
    sort: ItemSort = "added",
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> ItemPage:
    return ctx.library.list_items(collection_id, q, status, sort, offset, limit)


@router.get("/items/{item_id}", response_model=ItemDetail)
def get_item(ctx: Ctx, item_id: str) -> ItemDetail:
    item = ctx.library.get_item(item_id)
    if item is None:
        raise HTTPException(404, "item not found")
    return item


@router.post("/sync", response_model=JobOut, status_code=202)
def sync(ctx: Ctx, body: SyncRequest | None = None) -> JobOut:
    """从 Zotero 本地 API 同步，返回 sync 任务（进度见 /jobs/stream）。"""
    return ctx.library.request_sync(body.collection_key if body else None)


@router.post("/import-file", response_model=ImportFileResult)
def import_file(ctx: Ctx, body: ImportFileRequest) -> ImportFileResult:
    try:
        item_id, created = ctx.library.import_file(Path(body.path))
    except InvalidImportError as e:
        raise HTTPException(400, str(e)) from e
    return ImportFileResult(item=ctx.library.get_item(item_id), created=created)
