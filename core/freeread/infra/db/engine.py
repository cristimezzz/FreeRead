"""SQLite 引擎与会话。见 docs/03-data-model.md §1 的约定。"""

import json
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

SessionFactory = sessionmaker[Session]


def _set_pragmas(dbapi_conn, _record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys = ON")
    cur.execute("PRAGMA journal_mode = WAL")
    cur.execute("PRAGMA synchronous = NORMAL")
    cur.execute("PRAGMA busy_timeout = 5000")
    cur.close()


def make_engine(db_path: Path) -> Engine:
    # API 的同步路由跑在线程池里，worker 用 asyncio.to_thread，所以连接要允许跨线程。
    engine = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False},
        # 默认 ensure_ascii=True 会把中文存成 \uXXXX，导致对 JSON 列（如 authors）的 LIKE 搜索匹配不到。
        json_serializer=lambda obj: json.dumps(obj, ensure_ascii=False),
    )
    event.listen(engine, "connect", _set_pragmas)
    return engine


def make_session_factory(engine: Engine) -> SessionFactory:
    return sessionmaker(engine, expire_on_commit=False)
