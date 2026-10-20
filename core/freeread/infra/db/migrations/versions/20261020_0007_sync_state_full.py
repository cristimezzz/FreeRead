"""sync_state.last_full_sync_at

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-20 22:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("sync_state", schema=None) as batch_op:
        batch_op.add_column(sa.Column("last_full_sync_at", sa.String(), nullable=True))
    # M1 的同步都是全量
    op.execute("UPDATE sync_state SET last_full_sync_at = last_synced_at")


def downgrade() -> None:
    with op.batch_alter_table("sync_state", schema=None) as batch_op:
        batch_op.drop_column("last_full_sync_at")
