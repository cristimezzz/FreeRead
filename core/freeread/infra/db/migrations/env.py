"""Alembic 环境。运行时由 freeread.infra.db.migrate 传入 engine；
命令行（cd core && alembic ...）时使用 alembic.ini 里的 sqlalchemy.url。"""

from alembic import context
from sqlalchemy import create_engine

from freeread.infra.db import models  # noqa: F401  注册所有表
from freeread.infra.db.base import Base, include_name

config = context.config
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = config.attributes.get("engine") or create_engine(
        config.get_main_option("sqlalchemy.url")
    )
    with engine.connect() as conn:
        context.configure(
            connection=conn,
            target_metadata=target_metadata,
            render_as_batch=True,
            include_name=include_name,
        )
        with context.begin_transaction():
            context.run_migrations()
        conn.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
