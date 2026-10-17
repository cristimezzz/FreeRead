"""启动时自动升级数据库；升级前备份。见 docs/03-data-model.md §9。

迁移脚本位于本包的 migrations/ 下，运行时不依赖 alembic.ini（sidecar 中没有）。
"""

import logging
import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine

MIGRATIONS_DIR = Path(__file__).with_name("migrations")

log = logging.getLogger(__name__)


def alembic_config(engine: Engine) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.attributes["engine"] = engine
    return cfg


def current_revision(engine: Engine) -> str | None:
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def head_revision() -> str | None:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    return ScriptDirectory.from_config(cfg).get_current_head()


def backup(db_path: Path, dest: Path) -> None:
    """用 SQLite 在线备份 API 复制（WAL 中未合并的页也会带上）。"""
    src = sqlite3.connect(db_path)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def upgrade(engine: Engine, db_path: Path) -> Path | None:
    """升级到 head。已有数据且需要升级时先备份为 freeread.db.bak-<旧版本>，返回备份路径。"""
    current = current_revision(engine)
    head = head_revision()
    if current == head:
        return None
    backup_path = None
    if current is not None:
        backup_path = db_path.with_name(f"{db_path.name}.bak-{current}")
        backup(db_path, backup_path)
        log.info("database backed up to %s", backup_path)
    command.upgrade(alembic_config(engine), "head")
    log.info("database upgraded %s -> %s", current, head)
    return backup_path
