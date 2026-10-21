"""qa tree: qa_nodes.anchor and title, index on parent_id; old linear sessions become one chain

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-23 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _chain_orphans() -> None:
    """M2 的对话是线性的：除每个对话的第一轮外，parent_id 为空的接到前一轮上。"""
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id, session_id, parent_id FROM qa_nodes ORDER BY session_id, created_at, id"
        )
    ).all()
    prev: dict[str, str] = {}
    for node_id, session_id, parent_id in rows:
        if parent_id is None and session_id in prev:
            conn.execute(
                sa.text("UPDATE qa_nodes SET parent_id = :p WHERE id = :id"),
                {"p": prev[session_id], "id": node_id},
            )
        prev[session_id] = node_id


def upgrade() -> None:
    with op.batch_alter_table("qa_nodes", schema=None) as batch_op:
        batch_op.add_column(sa.Column("anchor", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("title", sa.Text(), nullable=False, server_default=""))
        batch_op.create_index(
            "ix_qa_nodes_session_id_parent_id", ["session_id", "parent_id"], unique=False
        )
    _chain_orphans()


def downgrade() -> None:
    with op.batch_alter_table("qa_nodes", schema=None) as batch_op:
        batch_op.drop_index("ix_qa_nodes_session_id_parent_id")
        batch_op.drop_column("title")
        batch_op.drop_column("anchor")
