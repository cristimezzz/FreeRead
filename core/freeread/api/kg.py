"""知识图谱（每篇论文一张图）：抽取与查询。见 docs/m3/kg.md。"""

from fastapi import APIRouter, HTTPException

from freeread.api.deps import Ctx
from freeread.api.glossary import preflight_http
from freeread.infra.jobs.queue import JobOut
from freeread.services.doc_blocks import DocumentNotReady
from freeread.services.kg import DocGraphOut
from freeread.services.llm_preflight import PreflightError

router = APIRouter(tags=["kg"])


@router.post("/documents/{doc_id}/kg/extract", response_model=JobOut, status_code=202)
def extract_graph(ctx: Ctx, doc_id: str) -> JobOut:
    """排队抽取（已有同一文档的任务时返回它）。重新抽取整体替换这篇的图。"""
    try:
        return ctx.kg.request_extract(doc_id)
    except DocumentNotReady as e:
        raise HTTPException(409, str(e)) from e
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except PreflightError as e:
        raise preflight_http(e) from e


@router.get("/documents/{doc_id}/kg", response_model=DocGraphOut)
def doc_graph(ctx: Ctx, doc_id: str) -> DocGraphOut:
    """本篇的实体（含出现的块）和关系（含出处块），实体按重要性排序。"""
    try:
        return ctx.kg.doc_graph(doc_id)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
