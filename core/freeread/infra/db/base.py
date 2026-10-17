"""SQLAlchemy 基础设施：声明基类、ID 与时间戳约定。见 docs/03-data-model.md §1。"""

import os
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


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def new_ulid() -> str:
    """26 位 Crockford Base32 ULID：48 位毫秒时间戳 + 80 位随机数，按时间可排序。"""
    value = (time.time_ns() // 1_000_000) << 80 | int.from_bytes(os.urandom(10), "big")
    return "".join(_CROCKFORD[(value >> shift) & 31] for shift in range(125, -1, -5))


def utcnow() -> str:
    """UTC ISO8601 文本，精确到毫秒，例如 2026-10-18T08:00:00.123Z。"""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
