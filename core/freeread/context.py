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
from freeread.infra.llm.default_gateway import DefaultGateway
from freeread.infra.llm.prompts import PromptRegistry
from freeread.infra.llm.secrets import SecretStore
from freeread.infra.zotero.local_api import LocalApiConnector
from freeread.services.library import LibraryService
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
    library: LibraryService
    secrets: SecretStore
    prompts: PromptRegistry
    llm: DefaultGateway

    @classmethod
    def open(cls, data_dir: Path, secrets: SecretStore | None = None) -> "AppContext":
        """创建数据目录、升级数据库。任务 worker 要等事件循环起来后再 start。

        secrets 省略时从环境变量 FREEREAD_SECRETS 读取（Rust 壳注入，见 secrets.py）。
        """
        paths = DataPaths(data_dir).ensure()
        engine = make_engine(paths.db)
        migrate.upgrade(engine, paths.db)
        sessions = make_session_factory(engine)
        bus = EventBus()
        jobs = JobQueue(sessions, bus)
        worker = JobWorker(jobs, bus)
        library = LibraryService(sessions, paths, jobs, LocalApiConnector)
        worker.register("sync", library.run_sync_job)
        settings = SettingsService(sessions)
        secrets = secrets if secrets is not None else SecretStore.from_env()
        return cls(
            paths=paths,
            engine=engine,
            sessions=sessions,
            bus=bus,
            jobs=jobs,
            worker=worker,
            settings=settings,
            library=library,
            secrets=secrets,
            prompts=PromptRegistry(),
            llm=DefaultGateway(settings, sessions, secrets),
        )

    def close(self) -> None:
        self.engine.dispose()
