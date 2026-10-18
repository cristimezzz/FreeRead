"""文内检索：关键词（FTS5）+ 语义（sqlite-vec）混合。"""

from fastapi import APIRouter, HTTPException, Query

from freeread.api.deps import Ctx
from freeread.services.search import SearchResponse

router = APIRouter(tags=["search"])


@router.get("/documents/{doc_id}/search", response_model=SearchResponse)
async def search_document(
    ctx: Ctx,
    doc_id: str,
    q: str = Query(max_length=500),
    k: int = Query(default=20, ge=1, le=100),
) -> SearchResponse:
    try:
        return await ctx.search.search_document(doc_id, q, k)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
