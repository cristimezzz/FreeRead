"""路由公共依赖。"""

from typing import Annotated

from fastapi import Depends, Request

from freeread.context import AppContext


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


Ctx = Annotated[AppContext, Depends(get_ctx)]
