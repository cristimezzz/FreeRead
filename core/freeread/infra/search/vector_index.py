"""向量索引。ADR-0002：检索走 VectorIndex 接口，以后可换 LanceDB 等。

SqliteVecIndex 用 freeread.db 里的 vec0 虚拟表 vec_chunks_<dim>：
    vec_chunks_<dim>(chunk_rowid integer primary key, doc_id text partition key,
                     embedding float[dim] distance_metric=cosine, chunk_size=128)
chunk_rowid 对应 embedding_chunks.rowid。维度取决于模型，所以表在运行时按当前模型创建；
当前模型和维度记在 settings 表的内部键 _vector_index 里（不属于 AppSettings）。
换模型时 clear() 清空，再由第一个嵌入任务 ensure() 按新维度建表（或复用同维度的空表）。
"""

from dataclasses import dataclass
from typing import Protocol

import numpy as np
import sqlite_vec
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from freeread.infra.db.models import SettingRow

STATE_KEY = "_vector_index"
# vec0 每个分区（文档）至少占一个存储块；默认 1024 行，而一篇论文约 100–250 个 chunk，
# 默认值下文件是向量本身的 6–7 倍。128 时约 1.7 倍，单篇检索 <1 ms（见 docs/m2/README.md）。
CHUNK_SIZE = 128


class IndexMismatch(RuntimeError):
    pass


@dataclass(frozen=True)
class IndexState:
    model: str
    dim: int


@dataclass
class VectorHit:
    chunk_rowid: int
    distance: float  # cosine 距离，0 为完全相同


class VectorIndex(Protocol):
    def state(self, s: Session) -> IndexState | None: ...

    def clear(self, s: Session) -> None:
        """删除所有向量和索引状态（换模型时）。"""

    def ensure(self, s: Session, model: str, dim: int) -> None:
        """索引不存在时按模型 / 维度创建；已存在但模型不同时抛 IndexMismatch。"""

    def vectors(self, s: Session, rowids: list[int]) -> dict[int, list[float]]: ...

    def drop_unused(self, engine: Engine) -> list[str]: ...

    def upsert(self, s: Session, doc_id: str, rows: list[tuple[int, list[float]]]) -> None: ...

    def delete_doc(self, s: Session, doc_id: str) -> None: ...

    def knn(
        self, s: Session, vector: list[float], k: int, doc_id: str | None = None
    ) -> list[VectorHit]: ...


class SqliteVecIndex:
    prefix = "vec_chunks_"

    def _table(self, dim: int) -> str:
        return f"{self.prefix}{int(dim)}"

    def _tables(self, s) -> list[str]:
        # 只要主表 vec_chunks_<dim>，不要 vec0 的影子表（vec_chunks_<dim>_info 等）
        names = s.scalars(
            text("SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE :p"),
            {"p": self.prefix + "%"},
        )
        return [n for n in names if n.removeprefix(self.prefix).isdigit()]

    def _current(self, s: Session) -> str | None:
        st = self.state(s)
        return self._table(st.dim) if st else None

    def state(self, s: Session) -> IndexState | None:
        row = s.get(SettingRow, STATE_KEY)
        if row is None:
            return None
        st = IndexState(row.value["model"], int(row.value["dim"]))
        return st if self._table(st.dim) in self._tables(s) else None

    def clear(self, s: Session) -> None:
        # 不 DROP：WAL 模式下在显式事务里 DROP vec0 表会报 "SQL logic error"。
        # 清空所有维度的表即可，空表由 drop_unused 在事务外删掉。
        for t in self._tables(s):
            s.execute(text(f"DELETE FROM {t}"))
        row = s.get(SettingRow, STATE_KEY)
        if row is not None:
            s.delete(row)
            s.flush()

    def ensure(self, s: Session, model: str, dim: int) -> None:
        state = self.state(s)
        if state is not None:
            if state != IndexState(model, int(dim)):
                raise IndexMismatch(f"向量索引属于 {state.model}（{state.dim} 维），当前为 {model}")
            return
        table = self._table(dim)
        s.execute(
            text(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS {table} USING vec0("
                "chunk_rowid integer primary key, doc_id text partition key, "
                f"embedding float[{int(dim)}] distance_metric=cosine, chunk_size={CHUNK_SIZE})"
            )
        )
        s.execute(text(f"DELETE FROM {table}"))
        s.merge(SettingRow(key=STATE_KEY, value={"model": model, "dim": int(dim)}))

    def drop_unused(self, engine: Engine) -> list[str]:
        """删除不是当前维度的向量表。必须在 autocommit 连接上执行（见 clear）。"""
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            current = self._current(Session(bind=conn))
            dropped = [t for t in self._tables(conn) if t != current]
            for t in dropped:
                conn.execute(text(f"DROP TABLE {t}"))
        return dropped

    def vectors(self, s: Session, rowids: list[int]) -> dict[int, list[float]]:
        table = self._current(s)
        if not rowids or table is None:
            return {}
        out = {}
        for start in range(0, len(rowids), 500):
            marks = ",".join(str(int(r)) for r in rowids[start : start + 500])
            for r, blob in s.execute(
                text(f"SELECT chunk_rowid, embedding FROM {table} WHERE chunk_rowid IN ({marks})")
            ):
                out[r] = np.frombuffer(blob, dtype=np.float32).tolist()
        return out

    def upsert(self, s: Session, doc_id: str, rows: list[tuple[int, list[float]]]) -> None:
        table = self._current(s)
        if not rows:
            return
        if table is None:
            raise IndexMismatch("向量索引尚未创建，先调用 ensure()")
        s.execute(text(f"DELETE FROM {table} WHERE chunk_rowid = :r"), [{"r": r} for r, _ in rows])
        s.execute(
            text(f"INSERT INTO {table}(chunk_rowid, doc_id, embedding) VALUES (:r, :d, :e)"),
            [{"r": r, "d": doc_id, "e": sqlite_vec.serialize_float32(v)} for r, v in rows],
        )

    def delete_doc(self, s: Session, doc_id: str) -> None:
        for t in self._tables(s):
            s.execute(text(f"DELETE FROM {t} WHERE doc_id = :d"), {"d": doc_id})

    def knn(
        self, s: Session, vector: list[float], k: int, doc_id: str | None = None
    ) -> list[VectorHit]:
        table = self._current(s)
        if table is None:
            return []
        where = "embedding MATCH :v AND k = :k" + (" AND doc_id = :d" if doc_id else "")
        rows = s.execute(
            text(f"SELECT chunk_rowid, distance FROM {table} WHERE {where} ORDER BY distance"),
            {"v": sqlite_vec.serialize_float32(vector), "k": k, "d": doc_id},
        ).all()
        return [VectorHit(r, d) for r, d in rows]
