"""kg merge suggestions

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-21 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "kg_merge_suggestions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("entity_id", sa.String(), nullable=False),
        sa.Column("candidate_id", sa.String(), nullable=False),
        sa.Column("doc_id", sa.String(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["kg_entities.id"],
            name=op.f("fk_kg_merge_suggestions_candidate_id_kg_entities"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["doc_id"],
            ["documents.doc_id"],
            name=op.f("fk_kg_merge_suggestions_doc_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["kg_entities.id"],
            name=op.f("fk_kg_merge_suggestions_entity_id_kg_entities"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kg_merge_suggestions")),
        sa.UniqueConstraint(
            "entity_id", "candidate_id", name=op.f("uq_kg_merge_suggestions_entity_id_candidate_id")
        ),
    )
    with op.batch_alter_table("kg_merge_suggestions", schema=None) as batch_op:
        batch_op.create_index("ix_kg_merge_suggestions_doc_id", ["doc_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("kg_merge_suggestions", schema=None) as batch_op:
        batch_op.drop_index("ix_kg_merge_suggestions_doc_id")

    op.drop_table("kg_merge_suggestions")
