"""SQLite 引擎与会话。见 docs/03-data-model.md §1 的约定。"""

from pathlib import Path

import sqlite_vec
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

SessionFactory = sessionmaker[Session]


def _set_pragmas(dbapi_conn, _record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys = ON")
    cur.execute("PRAGMA journal_mode = WAL")
    cur.execute("PRAGMA synchronous = NORMAL")
    cur.execute("PRAGMA busy_timeout = 5000")
    # 语句日志 / 临时索引放内存，不写系统临时目录（vec0 建表、大批量 DML 都会用到）
    cur.execute("PRAGMA temp_store = MEMORY")
    cur.close()
    # sqlite-vec：向量索引（vec0 虚拟表，见 freeread/infra/search/vector_index.py）。
    # 只在加载期间打开扩展加载，避免 SQL 里的 load_extension() 被滥用。
    dbapi_conn.enable_load_extension(True)
    try:
        sqlite_vec.load(dbapi_conn)
    finally:
        dbapi_conn.enable_load_extension(False)


def make_engine(db_path: Path) -> Engine:
    # API 的同步路由跑在线程池里，worker 用 asyncio.to_thread，所以连接要允许跨线程。
    engine = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    event.listen(engine, "connect", _set_pragmas)
    return engine


def make_session_factory(engine: Engine) -> SessionFactory:
    return sessionmaker(engine, expire_on_commit=False)
