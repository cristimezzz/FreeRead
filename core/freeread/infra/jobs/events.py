"""进程内事件总线：任务进度、翻译结果等推给 SSE 订阅者。

发布方可能在线程池里（FastAPI 同步路由、asyncio.to_thread），所以 publish 线程安全：
绑定事件循环后，非循环线程的发布会经 call_soon_threadsafe 转回循环线程。
"""

import asyncio
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

SUBSCRIBER_QUEUE_SIZE = 1000


@dataclass
class Event:
    type: str  # 如 "job"
    data: dict[str, Any]


@dataclass(eq=False)
class Subscription:
    queue: asyncio.Queue[Event] = field(
        default_factory=lambda: asyncio.Queue(SUBSCRIBER_QUEUE_SIZE)
    )
    # 消费太慢、队列满时置位；SSE 端据此让前端重新拉全量状态。
    overflowed: bool = False

    async def get(self) -> Event:
        return await self.queue.get()


class EventBus:
    def __init__(self) -> None:
        self._subs: set[Subscription] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: int | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._loop_thread = threading.get_ident()

    def publish(self, type: str, data: dict[str, Any]) -> None:
        event = Event(type, data)
        loop = self._loop
        if loop is None or threading.get_ident() == self._loop_thread:
            self._dispatch(event)
        elif not loop.is_closed():
            loop.call_soon_threadsafe(self._dispatch, event)

    def _dispatch(self, event: Event) -> None:
        for sub in list(self._subs):
            try:
                sub.queue.put_nowait(event)
            except asyncio.QueueFull:
                sub.overflowed = True

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[Subscription]:
        sub = Subscription()
        self._subs.add(sub)
        try:
            yield sub
        finally:
            self._subs.discard(sub)

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)
