"""SQLAlchemy 基础设施：声明基类、ID 与时间戳约定。见 docs/03-data-model.md §1。"""

import os
import threading
import time
from datetime import UTC, datetime

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

# 约束命名约定：Alembic 在 SQLite 上用 batch 模式改表时需要稳定的约束名。
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


# 虚拟表（FTS5、sqlite-vec）及其影子表不由 ORM 描述，autogenerate / 一致性检查时忽略。
VIRTUAL_TABLE_PREFIXES = ("blocks_fts", "vec_chunks")


def include_name(name, type_, _parent_names) -> bool:
    return not (type_ == "table" and name and name.startswith(VIRTUAL_TABLE_PREFIXES))


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


_ulid_lock = threading.Lock()
_last_ulid = 0


def new_ulid() -> str:
    """26 位 Crockford Base32 ULID：48 位毫秒时间戳 + 80 位随机数，按时间可排序。

    进程内单调递增（ULID 规范的 monotonic 模式）：同一毫秒内或时钟回拨时，
    在上一个值上加一，而不是重新取随机数。否则同毫秒生成的两行按 id 排序是随机的，
    依赖 (created_at, id) 定序的地方（任务队列、问答节点）会乱序。
    """
    global _last_ulid
    fresh = (time.time_ns() // 1_000_000) << 80 | int.from_bytes(os.urandom(10), "big")
    with _ulid_lock:
        value = _last_ulid = max(fresh, _last_ulid + 1)
    return "".join(_CROCKFORD[(value >> shift) & 31] for shift in range(125, -1, -5))


def utcnow() -> str:
    """UTC ISO8601 文本，精确到毫秒，例如 2026-10-18T08:00:00.123Z。"""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
