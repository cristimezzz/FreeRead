"""应用上下文：Core Service 运行期共享的资源，由 create_app 组装。"""

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine

from freeread.config import DataPaths
from freeread.infra.db import migrate
from freeread.infra.db.engine import SessionFactory, make_engine, make_session_factory
from freeread.infra.jobs.events import EventBus
from freeread.infra.jobs.queue import JobQueue
from freeread.infra.jobs.worker import JobWorker
from freeread.services.settings import SettingsService


@dataclass
class AppContext:
    paths: DataPaths
    engine: Engine
    sessions: SessionFactory
    bus: EventBus
    jobs: JobQueue
    worker: JobWorker
    settings: SettingsService

    @classmethod
    def open(cls, data_dir: Path) -> "AppContext":
        """创建数据目录、升级数据库。任务 worker 要等事件循环起来后再 start。"""
        paths = DataPaths(data_dir).ensure()
        engine = make_engine(paths.db)
        migrate.upgrade(engine, paths.db)
        sessions = make_session_factory(engine)
        bus = EventBus()
        jobs = JobQueue(sessions, bus)
        return cls(
            paths=paths,
            engine=engine,
            sessions=sessions,
            bus=bus,
            jobs=jobs,
            worker=JobWorker(jobs, bus),
            settings=SettingsService(sessions),
        )

    def close(self) -> None:
        self.engine.dispose()
