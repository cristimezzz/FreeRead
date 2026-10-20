"""annotations

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-20 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "annotations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("doc_id", sa.String(), nullable=False),
        sa.Column("block_id", sa.String(), nullable=False),
        sa.Column("start", sa.Integer(), nullable=True),
        sa.Column("end", sa.Integer(), nullable=True),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("color", sa.String(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["doc_id"],
            ["documents.doc_id"],
            name=op.f("fk_annotations_doc_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_annotations")),
    )
    with op.batch_alter_table("annotations", schema=None) as batch_op:
        batch_op.create_index(
            "ix_annotations_doc_id_block_id", ["doc_id", "block_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("annotations", schema=None) as batch_op:
        batch_op.drop_index("ix_annotations_doc_id_block_id")
    op.drop_table("annotations")
