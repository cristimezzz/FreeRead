"""glossary terms

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-20 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "glossary_terms",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("doc_id", sa.String(), nullable=True),
        sa.Column("lang", sa.String(), nullable=False),
        sa.Column("source_term", sa.Text(), nullable=False),
        sa.Column("term_key", sa.Text(), nullable=False),
        sa.Column("target_term", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("origin", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["doc_id"],
            ["documents.doc_id"],
            name=op.f("fk_glossary_terms_doc_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_glossary_terms")),
        sa.UniqueConstraint(
            "scope", "lang", "term_key", name=op.f("uq_glossary_terms_scope_lang_term_key")
        ),
    )


def downgrade() -> None:
    op.drop_table("glossary_terms")
