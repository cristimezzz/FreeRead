"""asyncio 任务执行器。见 docs/01-architecture.md §5.8。

- 每种任务注册一个 handler，可设并发上限（解析为 1，避免显存争用）和最大尝试次数；
- 没有注册 handler 的任务保持 queued，不会被取走；
- 用户取消 → cancelled；应用退出时被中断的任务放回 queued，下次启动继续。
"""

import asyncio
import contextlib
import logging
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from freeread.infra.jobs.events import EventBus
from freeread.infra.jobs.queue import FINISHED, JobOut, JobQueue, JobStatus

log = logging.getLogger(__name__)


@dataclass
class JobContext:
    job: JobOut
    queue: JobQueue

    async def report(self, progress: float, message: str | None = None) -> None:
        await asyncio.to_thread(self.queue.report, self.job.id, progress, message)


Handler = Callable[[JobContext], Awaitable[None]]


@dataclass(frozen=True)
class JobSpec:
    handler: Handler
    concurrency: int = 1
    max_attempts: int = 1


class JobWorker:
    def __init__(
        self,
        queue: JobQueue,
        bus: EventBus,
        max_concurrency: int = 4,
        poll_interval: float = 2.0,
    ) -> None:
        self.queue = queue
        self._bus = bus
        self._specs: dict[str, JobSpec] = {}
        self._max = max_concurrency
        self._poll = poll_interval
        self._running: dict[str, tuple[str, asyncio.Task[None]]] = {}  # job_id → (kind, task)
        self._user_cancelled: set[str] = set()
        self._wake = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []

    def register(
        self, kind: str, handler: Handler, *, concurrency: int = 1, max_attempts: int = 1
    ) -> None:
        self._specs[kind] = JobSpec(handler, concurrency, max_attempts)

    @property
    def running_ids(self) -> set[str]:
        return set(self._running)

    async def start(self) -> None:
        recovered = await asyncio.to_thread(self.queue.recover)
        if recovered:
            log.info("requeued %d interrupted jobs", recovered)
        self._tasks = [
            asyncio.create_task(self._loop(), name="job-worker"),
            asyncio.create_task(self._watch_events(), name="job-worker-events"),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        running = [task for _, task in self._running.values()]
        for task in running:
            task.cancel()
        await asyncio.gather(*self._tasks, *running, return_exceptions=True)
        self._tasks = []

    async def cancel(self, job_id: str) -> JobOut | None:
        if job_id in self._running:
            self._user_cancelled.add(job_id)
            self._running[job_id][1].cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._running[job_id][1]
            return await asyncio.to_thread(self.queue.get, job_id)
        return await asyncio.to_thread(self.queue.cancel, job_id)

    def wake(self) -> None:
        self._wake.set()

    async def _watch_events(self) -> None:
        # 新任务入队、任务结束（可能解锁依赖它的任务）时唤醒调度循环。
        async with self._bus.subscribe() as sub:
            while True:
                event = await sub.get()
                if event.type == "job" and event.data.get("status") != JobStatus.RUNNING:
                    self._wake.set()

    async def _loop(self) -> None:
        while True:
            self._wake.clear()
            try:
                await self._fill()
            except Exception:
                log.exception("job scheduling failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), self._poll)

    async def _fill(self) -> None:
        while len(self._running) < self._max:
            counts = Counter(kind for kind, _ in self._running.values())
            full = {k for k, spec in self._specs.items() if counts[k] >= spec.concurrency}
            job = await asyncio.to_thread(self.queue.claim_next, set(self._specs), full)
            if job is None:
                return
            task = asyncio.create_task(self._execute(job), name=f"job-{job.kind}-{job.id}")
            self._running[job.id] = (job.kind, task)

    async def _execute(self, job: JobOut) -> None:
        spec = self._specs[job.kind]
        try:
            await spec.handler(JobContext(job, self.queue))
        except asyncio.CancelledError:
            if job.id in self._user_cancelled:
                await asyncio.to_thread(self.queue.finish, job.id, JobStatus.CANCELLED)
            else:  # 应用退出：放回队列，下次启动继续
                await asyncio.to_thread(self.queue.finish, job.id, JobStatus.QUEUED)
            raise
        except Exception as e:
            log.exception("job %s (%s) failed", job.id, job.kind)
            error = f"{type(e).__name__}: {e}"
            status = JobStatus.QUEUED if job.attempts < spec.max_attempts else JobStatus.FAILED
            await asyncio.to_thread(self.queue.finish, job.id, status, error)
        else:
            current = await asyncio.to_thread(self.queue.get, job.id)
            if current is not None and current.status not in FINISHED:
                await asyncio.to_thread(self.queue.finish, job.id, JobStatus.DONE)
        finally:
            self._running.pop(job.id, None)
            self._user_cancelled.discard(job.id)
            self._wake.set()
