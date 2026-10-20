"""知识图谱：抽取、查询、手动合并 / 拆分。见 docs/m3/kg.md。"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response

from freeread.api.deps import Ctx
from freeread.api.glossary import preflight_http
from freeread.domain.kg.schema import EntityType
from freeread.infra.jobs.queue import JobOut
from freeread.services.doc_blocks import DocumentNotReady
from freeread.services.kg import (
    DocGraphOut,
    EntityDetailOut,
    EntityOut,
    EntityPatch,
    KGEditError,
    MergeIn,
    SplitIn,
    SubgraphOut,
)
from freeread.services.llm_preflight import PreflightError

router = APIRouter(tags=["kg"])


@router.post("/documents/{doc_id}/kg/extract", response_model=JobOut, status_code=202)
def extract_graph(ctx: Ctx, doc_id: str) -> JobOut:
    """排队抽取（已有同一文档的任务时返回它）。重新抽取只替换该文档的提及和关系。"""
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
    """本篇的实体（含在本篇出现的块）和关系（含出处块）；用户删除的关系不返回。"""
    try:
        return ctx.kg.doc_graph(doc_id)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e


@router.get("/kg/entities", response_model=list[EntityOut])
def search_entities(
    ctx: Ctx,
    q: Annotated[str, Query(max_length=200)] = "",
    type: Annotated[EntityType | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[EntityOut]:
    """按名称 / 别名搜索全库实体（合并时选目标用）。"""
    return ctx.kg.search_entities(q, type, limit)


@router.get("/kg/entities/{entity_id}", response_model=EntityDetailOut)
def entity_detail(ctx: Ctx, entity_id: str) -> EntityDetailOut:
    """实体在全库的提及和关系，带文献标题。"""
    try:
        return ctx.kg.entity_detail(entity_id)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e


@router.patch("/kg/entities/{entity_id}", response_model=EntityOut)
def update_entity(ctx: Ctx, entity_id: str, body: EntityPatch) -> EntityOut:
    try:
        return ctx.kg.update_entity(entity_id, body)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e


@router.post("/kg/entities/{entity_id}/merge", response_model=EntityOut)
def merge_entities(ctx: Ctx, entity_id: str, body: MergeIn) -> EntityOut:
    """把 source_ids 并入这个实体。"""
    try:
        return ctx.kg.merge(entity_id, body.source_ids)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except KGEditError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/kg/entities/{entity_id}/split", response_model=EntityOut)
def split_entity(ctx: Ctx, entity_id: str, body: SplitIn) -> EntityOut:
    """把选中的别名拆成新实体，返回新实体。"""
    try:
        return ctx.kg.split(entity_id, body.aliases)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except KGEditError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/kg/suggestions/{suggestion_id}/accept", response_model=EntityOut)
def accept_suggestion(ctx: Ctx, suggestion_id: str) -> EntityOut:
    """确认合并建议：把建议里的实体并入候选实体，返回合并后的实体。"""
    try:
        return ctx.kg.accept_suggestion(suggestion_id)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e


@router.post("/kg/suggestions/{suggestion_id}/dismiss", status_code=204)
def dismiss_suggestion(ctx: Ctx, suggestion_id: str) -> Response:
    """否决合并建议：记为不是同一个，以后不再建议。"""
    try:
        ctx.kg.dismiss_suggestion(suggestion_id)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    return Response(status_code=204)


@router.delete("/kg/relations/{relation_id}", status_code=204)
def reject_relation(ctx: Ctx, relation_id: str) -> Response:
    """删除一条关系（标记 rejected，重新抽取不会加回）。"""
    if not ctx.kg.reject_relation(relation_id):
        raise HTTPException(404, "relation not found")
    return Response(status_code=204)


@router.get("/kg/subgraph", response_model=SubgraphOut)
def subgraph(
    ctx: Ctx,
    doc_id: Annotated[str | None, Query()] = None,
    entity_id: Annotated[str | None, Query()] = None,
) -> SubgraphOut:
    """按文档或实体（一跳）取子图。"""
    try:
        return ctx.kg.subgraph(doc_id, entity_id)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except KGEditError as e:
        raise HTTPException(400, str(e)) from e
