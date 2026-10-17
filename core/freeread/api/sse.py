"""Server-Sent Events 编码。

前端用 fetch 流式读取（原生 EventSource 不能带 X-FreeRead-Token 头），格式仍遵循 SSE 规范。
"""

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from fastapi.responses import StreamingResponse

from freeread.infra.jobs.events import EventBus

HEARTBEAT_SECONDS = 15.0

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def encode(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def bus_stream(
    bus: EventBus,
    types: set[str],
    is_disconnected: Callable[[], Awaitable[bool]],
    heartbeat: float = HEARTBEAT_SECONDS,
) -> AsyncIterator[str]:
    """把总线上指定类型的事件转成 SSE。

    先发 `ready`，订阅建立后客户端再拉全量状态，才不会漏掉中间的事件。
    订阅者积压溢出时发 `resync`，提示客户端重新拉全量状态。
    """
    async with bus.subscribe() as sub:
        yield encode("ready", {})
        while not await is_disconnected():
            if sub.overflowed:
                sub.overflowed = False
                yield encode("resync", {})
            try:
                event = await asyncio.wait_for(sub.get(), heartbeat)
            except TimeoutError:
                yield ": ping\n\n"
                continue
            if event.type in types:
                yield encode(event.type, event.data)


def sse_response(stream: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(stream, media_type="text/event-stream", headers=SSE_HEADERS)
