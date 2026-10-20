"""knowledge graph: kg_entities, kg_entity_aliases, kg_mentions, kg_relations, kg_distinct

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-20 23:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "kg_entities",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("name_norm", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("origin", sa.String(), nullable=False),
        sa.Column("embedding", sa.LargeBinary(), nullable=True),
        sa.Column("embedding_model", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kg_entities")),
    )
    with op.batch_alter_table("kg_entities", schema=None) as batch_op:
        batch_op.create_index("ix_kg_entities_type_name_norm", ["type", "name_norm"], unique=False)

    op.create_table(
        "kg_distinct",
        sa.Column("a_id", sa.String(), nullable=False),
        sa.Column("b_id", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["a_id"],
            ["kg_entities.id"],
            name=op.f("fk_kg_distinct_a_id_kg_entities"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["b_id"],
            ["kg_entities.id"],
            name=op.f("fk_kg_distinct_b_id_kg_entities"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("a_id", "b_id", name=op.f("pk_kg_distinct")),
    )
    op.create_table(
        "kg_entity_aliases",
        sa.Column("entity_id", sa.String(), nullable=False),
        sa.Column("alias_norm", sa.Text(), nullable=False),
        sa.Column("alias", sa.Text(), nullable=False),
        sa.Column("origin", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["kg_entities.id"],
            name=op.f("fk_kg_entity_aliases_entity_id_kg_entities"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("entity_id", "alias_norm", name=op.f("pk_kg_entity_aliases")),
    )
    with op.batch_alter_table("kg_entity_aliases", schema=None) as batch_op:
        batch_op.create_index("ix_kg_entity_aliases_alias_norm", ["alias_norm"], unique=False)

    op.create_table(
        "kg_mentions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("entity_id", sa.String(), nullable=False),
        sa.Column("doc_id", sa.String(), nullable=False),
        sa.Column("block_id", sa.String(), nullable=False),
        sa.Column("surface", sa.Text(), nullable=False),
        sa.Column("surface_norm", sa.Text(), nullable=False),
        sa.Column("extractor", sa.String(), nullable=False),
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
        sa.Column("src_id", sa.String(), nullable=False),
        sa.Column("dst_id", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("attrs", sa.JSON(), nullable=False),
        sa.Column("doc_id", sa.String(), nullable=False),
        sa.Column("source_block_id", sa.String(), nullable=False),
        sa.Column("src_surface", sa.Text(), nullable=False),
        sa.Column("dst_surface", sa.Text(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("extractor", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
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
        batch_op.create_index("ix_kg_relations_dst_id_type", ["dst_id", "type"], unique=False)
        batch_op.create_index("ix_kg_relations_src_id_type", ["src_id", "type"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("kg_relations", schema=None) as batch_op:
        batch_op.drop_index("ix_kg_relations_src_id_type")
        batch_op.drop_index("ix_kg_relations_dst_id_type")
        batch_op.drop_index("ix_kg_relations_doc_id")

    op.drop_table("kg_relations")
    with op.batch_alter_table("kg_mentions", schema=None) as batch_op:
        batch_op.drop_index("ix_kg_mentions_entity_id")
        batch_op.drop_index("ix_kg_mentions_doc_id")

    op.drop_table("kg_mentions")
    with op.batch_alter_table("kg_entity_aliases", schema=None) as batch_op:
        batch_op.drop_index("ix_kg_entity_aliases_alias_norm")

    op.drop_table("kg_entity_aliases")
    op.drop_table("kg_distinct")
    with op.batch_alter_table("kg_entities", schema=None) as batch_op:
        batch_op.drop_index("ix_kg_entities_type_name_norm")

    op.drop_table("kg_entities")
