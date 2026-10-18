"""任务列表、取消与进度推送。"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from freeread.api.deps import Ctx
from freeread.api.sse import bus_stream, sse_response
from freeread.infra.jobs.queue import JobOut, JobStatus

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobOut])
def list_jobs(
    ctx: Ctx,
    status: Annotated[list[JobStatus] | None, Query()] = None,
    kind: str | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[JobOut]:
    return ctx.jobs.list(status, kind, limit)


@router.get(
    "/stream",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def stream_jobs(ctx: Ctx, request: Request):
    """SSE：`ready` 之后，任务变化发 `job`（数据同 JobOut），文档解析状态变化发 `document`
    （数据同 DocumentOut，ready 时前端应重新拉 IR）；`resync` 表示需重新拉全量状态。"""
    return sse_response(bus_stream(ctx.bus, {"job", "document"}, request.is_disconnected))


@router.get("/{job_id}", response_model=JobOut)
def get_job(ctx: Ctx, job_id: str) -> JobOut:
    job = ctx.jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return job


@router.post("/{job_id}/cancel", response_model=JobOut)
async def cancel_job(ctx: Ctx, job_id: str) -> JobOut:
    job = await ctx.worker.cancel(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return job
