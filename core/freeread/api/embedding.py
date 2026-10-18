"""嵌入：来源状态、内置模型下载、重建索引。"""

from fastapi import APIRouter, HTTPException

from freeread.api.deps import Ctx
from freeread.infra.jobs.queue import JobOut
from freeread.services.embed import EmbeddingStatus, EmbedNotReady

router = APIRouter(prefix="/embedding", tags=["embedding"])


@router.get("/status", response_model=EmbeddingStatus)
def embedding_status(ctx: Ctx) -> EmbeddingStatus:
    return ctx.embed.status()


@router.post("/download", response_model=JobOut, status_code=202)
def download_model(ctx: Ctx) -> JobOut:
    """下载当前设置的内置嵌入模型（已有下载任务时返回它）。"""
    try:
        return ctx.embed.request_download()
    except EmbedNotReady as e:
        raise HTTPException(422, str(e)) from e


@router.post("/rebuild", response_model=list[str], status_code=202)
def rebuild_index(ctx: Ctx) -> list[str]:
    """清空向量索引，所有已解析文档重新嵌入。返回新建任务的 ID。"""
    try:
        return ctx.embed.rebuild()
    except EmbedNotReady as e:
        raise HTTPException(409, {"code": e.code, "message": str(e)}) from e
