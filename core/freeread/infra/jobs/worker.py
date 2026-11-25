"""asyncio 任务执行器。见 docs/01-architecture.md §5.8。

- 每种任务注册一个 handler，可设并发上限和最大尝试次数；
- 没有注册 handler 的任务保持 queued，不会被取走；
- 用户取消 → cancelled；应用退出时被中断的任务放回 queued，下次启动继续。
"""

import asyncio
import contextlib
import logging
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import ColumnElement

from freeread.infra.jobs.events import EventBus
from freeread.infra.jobs.queue import JobOut, JobQueue, JobStatus

log = logging.getLogger(__name__)


@dataclass
class JobContext:
    job: JobOut
    queue: JobQueue
    partition: str | None = None

    async def report(self, progress: float, message: str | None = None) -> None:
        await asyncio.to_thread(self.queue.report, self.job.id, progress, message)


Handler = Callable[[JobContext], Awaitable[None]]
Partitions = Callable[[], dict[str, tuple[int, ColumnElement[bool]]]]


@dataclass(frozen=True)
class JobSpec:
    handler: Handler
    concurrency: int = 1
    max_attempts: int = 1
    partitions: Partitions | None = None


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
        self._running: dict[str, tuple[str, str | None, asyncio.Task[None]]] = {}
        self._user_cancelled: set[str] = set()
        self._wake = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []

    def register(
        self,
        kind: str,
        handler: Handler,
        *,
        concurrency: int = 1,
        max_attempts: int = 1,
        partitions: Partitions | None = None,
    ) -> None:
        self._specs[kind] = JobSpec(handler, concurrency, max_attempts, partitions)

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
        running = [task for _, _, task in self._running.values()]
        for task in running:
            task.cancel()
        await asyncio.gather(*self._tasks, *running, return_exceptions=True)
        self._tasks = []

    async def cancel(self, job_id: str) -> JobOut | None:
        if job_id in self._running:
            self._user_cancelled.add(job_id)
            task = self._running[job_id][2]
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
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
            # 不用 asyncio.wait_for：3.11 上它会在 _wake 恰好被置位时吞掉 stop() 的取消，
            # 调度循环就永远不退出。asyncio.timeout 不会吞取消。
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(self._poll):
                    await self._wake.wait()

    async def _fill(self) -> None:
        regular = {
            kind: spec.concurrency for kind, spec in self._specs.items() if spec.partitions is None
        }
        for _ in range(self._max):
            counts = Counter(
                kind for kind, partition, _ in self._running.values() if partition is None
            )
            if sum(counts.values()) >= self._max:
                break
            eligible = {kind for kind, limit in regular.items() if counts[kind] < limit}
            if not await self._claim(eligible):
                break

        # 独立的并发额度允许 API 满载时继续调度其余后台任务。
        for kind, spec in self._specs.items():
            if spec.partitions is None:
                continue
            for partition, (limit, where) in (await asyncio.to_thread(spec.partitions)).items():
                active = sum((k, p) == (kind, partition) for k, p, _ in self._running.values())
                for _ in range(limit - active):
                    if not await self._claim({kind}, partition, where):
                        break

    async def _claim(
        self,
        kinds: set[str],
        partition: str | None = None,
        where: ColumnElement[bool] | None = None,
    ) -> bool:
        if not kinds:
            return False
        # 处理器可能已把任务放回队列，但还没从运行列表退出。
        job = await asyncio.to_thread(
            self.queue.claim_next, kinds, where=where, exclude_ids=tuple(self._running)
        )
        if job is None:
            return False
        task = asyncio.create_task(self._execute(job, partition), name=f"job-{job.kind}-{job.id}")
        self._running[job.id] = (job.kind, partition, task)
        return True

    async def _execute(self, job: JobOut, partition: str | None) -> None:
        spec = self._specs[job.kind]
        try:
            await spec.handler(JobContext(job, self.queue, partition))
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
            if current is not None and current.status == JobStatus.RUNNING:
                await asyncio.to_thread(self.queue.finish, job.id, JobStatus.DONE)
        finally:
            self._running.pop(job.id, None)
            self._user_cancelled.discard(job.id)
            self._wake.set()
