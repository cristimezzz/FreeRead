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
from freeread.infra.parsers.registry import ParserRegistry
from freeread.infra.zotero.local_api import LocalApiConnector
from freeread.services.embed import EmbedService
from freeread.services.library import LibraryService
from freeread.services.parse import ParseService
from freeread.services.search import SearchService
from freeread.services.settings import SettingsService
from freeread.services.summary import SummaryService
from freeread.services.translate import TranslateService


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
    parse: ParseService
    secrets: SecretStore
    prompts: PromptRegistry
    llm: DefaultGateway
    translate: TranslateService
    embed: EmbedService
    search: SearchService
    summary: SummaryService

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
        parse = ParseService(sessions, paths, jobs, bus, settings, ParserRegistry(paths.logs))
        worker.register("parse", parse.run_parse_job, concurrency=2)
        worker.register("parse_hq", parse.run_parse_hq_job, concurrency=1)
        secrets = secrets if secrets is not None else SecretStore.from_env()
        prompts = PromptRegistry()
        llm = DefaultGateway(settings, sessions, secrets)
        embed = EmbedService(sessions, paths, jobs, bus, settings, llm, engine=engine)
        worker.register("embed", embed.run_embed_job, concurrency=1)
        worker.register("model_download", embed.run_model_download_job, concurrency=1)
        parse.on_blocks_replaced = embed.enqueue_embed
        return cls(
            paths=paths,
            engine=engine,
            sessions=sessions,
            bus=bus,
            jobs=jobs,
            worker=worker,
            settings=settings,
            library=library,
            parse=parse,
            secrets=secrets,
            prompts=prompts,
            llm=llm,
            translate=TranslateService(sessions, settings, llm, prompts),
            embed=embed,
            search=SearchService(sessions, embed),
            summary=SummaryService(sessions, paths, settings, llm, prompts),
        )

    def close(self) -> None:
        self.engine.dispose()
