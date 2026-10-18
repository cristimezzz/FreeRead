"""embedding chunks and blocks_fts

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-18 21:00:00

向量表 vec_chunks_<dim> 不在这里建：维度取决于嵌入模型，由 SqliteVecIndex.ensure 在运行时创建。
"""

from collections.abc import Sequence
from types import SimpleNamespace

import sqlalchemy as sa
from alembic import op

from freeread.infra.search import fts

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "embedding_chunks",
        sa.Column("rowid", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("doc_id", sa.String(), nullable=False),
        sa.Column("ord", sa.Integer(), nullable=False),
        sa.Column("block_ids", sa.JSON(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("text_hash", sa.String(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["doc_id"],
            ["documents.doc_id"],
            name=op.f("fk_embedding_chunks_doc_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("rowid", name=op.f("pk_embedding_chunks")),
    )
    with op.batch_alter_table("embedding_chunks", schema=None) as batch_op:
        batch_op.create_index("ix_embedding_chunks_doc_id_ord", ["doc_id", "ord"], unique=False)
        batch_op.create_index(
            "ix_embedding_chunks_model_text_hash", ["model", "text_hash"], unique=False
        )

    bind = op.get_bind()
    bind.execute(sa.text(fts.CREATE_SQL))

    # 回填已有文档的全文索引（占位符展开要用 Python，不能只写 INSERT ... SELECT）
    blocks = sa.table(
        "blocks",
        sa.column("doc_id", sa.String),
        sa.column("block_id", sa.String),
        sa.column("ord", sa.Integer),
        sa.column("type", sa.String),
        sa.column("text", sa.Text),
        sa.column("inlines", sa.JSON),
        sa.column("html", sa.Text),
    )
    by_doc: dict[str, list] = {}
    for r in bind.execute(sa.select(blocks).order_by(blocks.c.doc_id, blocks.c.ord)):
        by_doc.setdefault(r.doc_id, []).append(SimpleNamespace(**r._mapping))
    for doc_id, rows in by_doc.items():
        fts.replace_doc(bind, doc_id, rows)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS blocks_fts")
    bind = op.get_bind()
    names = bind.scalars(
        sa.text("SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'vec_chunks_%'")
    ).all()
    for name in names:
        if name.removeprefix("vec_chunks_").isdigit():
            op.execute(f"DROP TABLE IF EXISTS {name}")
    op.execute("DELETE FROM settings WHERE key = '_vector_index'")
    with op.batch_alter_table("embedding_chunks", schema=None) as batch_op:
        batch_op.drop_index("ix_embedding_chunks_model_text_hash")
        batch_op.drop_index("ix_embedding_chunks_doc_id_ord")
    op.drop_table("embedding_chunks")
