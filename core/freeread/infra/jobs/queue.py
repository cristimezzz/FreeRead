"""SQLite 持久化任务队列。见 docs/01-architecture.md §5.8。

方法都是同步的（SQLite 操作很短）；worker 在事件循环里经 asyncio.to_thread 调用。
每次状态 / 进度变化都发布 "job" 事件。
"""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, update
from sqlalchemy.orm import aliased

from freeread.infra.db.base import utcnow
from freeread.infra.db.engine import SessionFactory
from freeread.infra.db.models import JobRow
from freeread.infra.jobs.events import EventBus


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


FINISHED = frozenset({JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED})


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    payload: dict[str, Any]
    status: JobStatus
    progress: float
    message: str | None
    depends_on: str | None
    attempts: int
    error: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None


class JobQueue:
    def __init__(self, sessions: SessionFactory, bus: EventBus) -> None:
        self._sessions = sessions
        self._bus = bus

    def _emit(self, row: JobRow) -> JobOut:
        out = JobOut.model_validate(row)
        self._bus.publish("job", out.model_dump(mode="json"))
        return out

    def enqueue(
        self, kind: str, payload: dict[str, Any] | None = None, depends_on: str | None = None
    ) -> JobOut:
        with self._sessions.begin() as s:
            row = JobRow(kind=kind, payload=payload or {}, depends_on=depends_on)
            s.add(row)
            s.flush()
            s.refresh(row)
            return self._emit(row)

    def get(self, job_id: str) -> JobOut | None:
        with self._sessions() as s:
            row = s.get(JobRow, job_id)
            return JobOut.model_validate(row) if row else None

    def list(
        self, statuses: list[JobStatus] | None = None, kind: str | None = None, limit: int = 100
    ) -> list[JobOut]:
        q = select(JobRow).order_by(JobRow.created_at.desc(), JobRow.id.desc()).limit(limit)
        if statuses:
            q = q.where(JobRow.status.in_(statuses))
        if kind:
            q = q.where(JobRow.kind == kind)
        with self._sessions() as s:
            return [JobOut.model_validate(r) for r in s.scalars(q)]

    def recover(self) -> int:
        """应用重启后把遗留的 running 任务放回队列。返回恢复的数量。"""
        with self._sessions.begin() as s:
            result = s.execute(
                update(JobRow)
                .where(JobRow.status == JobStatus.RUNNING)
                .values(status=JobStatus.QUEUED, started_at=None)
            )
            return result.rowcount

    def claim_next(self, kinds: set[str], exclude_kinds: set[str] = frozenset()) -> JobOut | None:
        """取出最早的可运行任务并置为 running。

        前置任务失败或取消的任务直接标记为 cancelled，不会运行。
        """
        kinds = kinds - exclude_kinds
        if not kinds:
            return None
        dep = aliased(JobRow)
        with self._sessions.begin() as s:
            blocked = s.scalars(
                select(JobRow)
                .join(dep, JobRow.depends_on == dep.id)
                .where(
                    JobRow.status == JobStatus.QUEUED,
                    dep.status.in_([JobStatus.FAILED, JobStatus.CANCELLED]),
                )
            ).all()
            for row in blocked:
                row.status = JobStatus.CANCELLED
                row.error = f"dependency {row.depends_on} did not complete"
                row.finished_at = utcnow()
                s.flush()
                self._emit(row)

            row = s.scalars(
                select(JobRow)
                .outerjoin(dep, JobRow.depends_on == dep.id)
                .where(
                    JobRow.status == JobStatus.QUEUED,
                    JobRow.kind.in_(kinds),
                    (JobRow.depends_on.is_(None)) | (dep.status == JobStatus.DONE),
                )
                .order_by(JobRow.created_at, JobRow.id)
                .limit(1)
            ).first()
            if row is None:
                return None
            row.status = JobStatus.RUNNING
            row.attempts += 1
            row.started_at = utcnow()
            row.error = None
            s.flush()
            return self._emit(row)

    def report(self, job_id: str, progress: float, message: str | None = None) -> None:
        with self._sessions.begin() as s:
            row = s.get(JobRow, job_id)
            if row is None or row.status != JobStatus.RUNNING:
                return
            row.progress = min(max(progress, 0.0), 1.0)
            row.message = message
            s.flush()
            self._emit(row)

    def finish(
        self, job_id: str, status: JobStatus, error: str | None = None, message: str | None = None
    ) -> JobOut | None:
        """running → done / failed / cancelled；也用于失败重试时放回 queued。"""
        with self._sessions.begin() as s:
            row = s.get(JobRow, job_id)
            if row is None:
                return None
            row.status = status
            row.error = error
            if message is not None:
                row.message = message
            if status == JobStatus.DONE:
                row.progress = 1.0
            if status in FINISHED:
                row.finished_at = utcnow()
            else:
                row.started_at = None
            s.flush()
            return self._emit(row)

    def cancel(self, job_id: str) -> JobOut | None:
        """取消排队中的任务。运行中的任务由 JobWorker.cancel 负责中断。"""
        with self._sessions.begin() as s:
            row = s.get(JobRow, job_id)
            if row is None or row.status != JobStatus.QUEUED:
                return JobOut.model_validate(row) if row else None
            row.status = JobStatus.CANCELLED
            row.finished_at = utcnow()
            s.flush()
            return self._emit(row)
