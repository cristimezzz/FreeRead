"""knowledge graph per document: entities belong to one document; drop cross-document tables

Old graphs are discarded (documents.kg_status back to pending); users re-extract.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-22 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _drop_all() -> None:
    for table in (
        "kg_merge_suggestions",
        "kg_relations",
        "kg_mentions",
        "kg_entity_aliases",
        "kg_distinct",
        "kg_entities",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    op.execute("UPDATE documents SET kg_status = 'pending'")


def upgrade() -> None:
    _drop_all()
    op.create_table(
        "kg_entities",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("doc_id", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("name_norm", sa.Text(), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["doc_id"],
            ["documents.doc_id"],
            name=op.f("fk_kg_entities_doc_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kg_entities")),
    )
    with op.batch_alter_table("kg_entities", schema=None) as batch_op:
        batch_op.create_index("ix_kg_entities_doc_id_type", ["doc_id", "type"], unique=False)

    op.create_table(
        "kg_mentions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("entity_id", sa.String(), nullable=False),
        sa.Column("doc_id", sa.String(), nullable=False),
        sa.Column("block_id", sa.String(), nullable=False),
        sa.Column("surface", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["doc_id"],
            ["documents.doc_id"],
            name=op.f("fk_kg_mentions_doc_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["kg_entities.id"],
            name=op.f("fk_kg_mentions_entity_id_kg_entities"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kg_mentions")),
    )
    with op.batch_alter_table("kg_mentions", schema=None) as batch_op:
        batch_op.create_index("ix_kg_mentions_doc_id", ["doc_id"], unique=False)
        batch_op.create_index("ix_kg_mentions_entity_id", ["entity_id"], unique=False)

    op.create_table(
        "kg_relations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("doc_id", sa.String(), nullable=False),
        sa.Column("src_id", sa.String(), nullable=False),
        sa.Column("dst_id", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("attrs", sa.JSON(), nullable=False),
        sa.Column("source_block_id", sa.String(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("extractor", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["doc_id"],
            ["documents.doc_id"],
            name=op.f("fk_kg_relations_doc_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dst_id"],
            ["kg_entities.id"],
            name=op.f("fk_kg_relations_dst_id_kg_entities"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["src_id"],
            ["kg_entities.id"],
            name=op.f("fk_kg_relations_src_id_kg_entities"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kg_relations")),
    )
    with op.batch_alter_table("kg_relations", schema=None) as batch_op:
        batch_op.create_index("ix_kg_relations_doc_id", ["doc_id"], unique=False)


def downgrade() -> None:
    # 回到 0009 的跨文档结构：单篇图谱无法还原成共享实体，同样清空
    import importlib.util
    from pathlib import Path

    _drop_all()
    for name in ("20261020_0008_kg", "20261021_0009_kg_merge_suggestions"):
        spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(f"{name}.py"))
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.upgrade()
