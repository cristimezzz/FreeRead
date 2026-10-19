"""qa sessions and nodes

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-19 20:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "qa_sessions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("doc_id", sa.String(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["doc_id"],
            ["documents.doc_id"],
            name=op.f("fk_qa_sessions_doc_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_qa_sessions")),
    )
    with op.batch_alter_table("qa_sessions", schema=None) as batch_op:
        batch_op.create_index(
            "ix_qa_sessions_doc_id_updated_at", ["doc_id", "updated_at"], unique=False
        )

    op.create_table(
        "qa_nodes",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("parent_id", sa.String(), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("citations", sa.JSON(), nullable=False),
        sa.Column("stats", sa.JSON(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("prompt_version", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["qa_nodes.id"],
            name=op.f("fk_qa_nodes_parent_id_qa_nodes"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["qa_sessions.id"],
            name=op.f("fk_qa_nodes_session_id_qa_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_qa_nodes")),
    )
    with op.batch_alter_table("qa_nodes", schema=None) as batch_op:
        batch_op.create_index(
            "ix_qa_nodes_session_id_created_at", ["session_id", "created_at"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("qa_nodes", schema=None) as batch_op:
        batch_op.drop_index("ix_qa_nodes_session_id_created_at")
    op.drop_table("qa_nodes")
    with op.batch_alter_table("qa_sessions", schema=None) as batch_op:
        batch_op.drop_index("ix_qa_sessions_doc_id_updated_at")
    op.drop_table("qa_sessions")
