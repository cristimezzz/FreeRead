"""应用设置（不含密钥）。"""

from fastapi import APIRouter

from freeread.api.deps import Ctx
from freeread.services.settings import AppSettings

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=AppSettings)
def get_settings(ctx: Ctx) -> AppSettings:
    return ctx.settings.get()


@router.put("", response_model=AppSettings)
def put_settings(ctx: Ctx, settings: AppSettings) -> AppSettings:
    saved = ctx.settings.put(settings)
    # 嵌入来源 / 模型可能变了，或刚确认了嵌入用的 provider：清理过期索引并给待嵌入文档排队
    ctx.embed.enqueue_missing()
    return saved
