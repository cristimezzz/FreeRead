import sqlite3
import time

from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, text

from freeread.config import DataPaths
from freeread.infra.db import migrate
from freeread.infra.db.base import Base, include_name, new_ulid, utcnow
from freeread.infra.db.engine import make_engine
from freeread.infra.db.models import SettingRow


def test_data_dir_layout(tmp_path):
    paths = DataPaths(tmp_path / "FreeRead").ensure()
    for d in ("documents", "zotero-snapshots", "models", "logs"):
        assert (tmp_path / "FreeRead" / d).is_dir()
    assert paths.document_dir("d_x") == tmp_path / "FreeRead" / "documents" / "d_x"


def test_fresh_database_upgrades_to_head_without_backup(tmp_path):
    db = tmp_path / "freeread.db"
    engine = make_engine(db)
    assert migrate.upgrade(engine, db) is None
    assert migrate.current_revision(engine) == migrate.head_revision()
    tables = set(inspect(engine).get_table_names())
    assert {"items", "documents", "blocks", "translations", "jobs", "settings"} <= tables
    assert list(tmp_path.glob("*.bak-*")) == []
    # 再次启动不做任何事
    assert migrate.upgrade(engine, db) is None


def test_pragmas(tmp_path):
    engine = make_engine(tmp_path / "freeread.db")
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"


def test_migrations_match_models(tmp_path):
    """模型改了却忘记生成迁移时失败。"""
    db = tmp_path / "freeread.db"
    engine = make_engine(db)
    migrate.upgrade(engine, db)
    with engine.connect() as conn:
        mc = MigrationContext.configure(conn, opts={"include_name": include_name})
        diff = compare_metadata(mc, Base.metadata)
    assert diff == []


def test_upgrade_backs_up_existing_database(tmp_path, monkeypatch):
    db = tmp_path / "freeread.db"
    engine = make_engine(db)
    migrate.upgrade(engine, db)
    with engine.begin() as conn:
        conn.execute(SettingRow.__table__.insert().values(key="k", value="v"))
    old = migrate.current_revision(engine)

    upgraded = []
    monkeypatch.setattr(migrate, "head_revision", lambda: "future")
    monkeypatch.setattr(migrate.command, "upgrade", lambda cfg, rev: upgraded.append(rev))
    backup = migrate.upgrade(engine, db)

    assert backup == tmp_path / f"freeread.db.bak-{old}"
    assert upgraded == ["head"]
    with sqlite3.connect(backup) as conn:
        assert conn.execute("SELECT key FROM settings").fetchall() == [("k",)]


def test_ulid_and_timestamps():
    a = new_ulid()
    time.sleep(0.002)
    b = new_ulid()
    assert len(a) == 26 and a < b
    assert utcnow().endswith("Z")
