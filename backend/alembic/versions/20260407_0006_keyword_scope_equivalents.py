"""Add keyword scope and equivalent terms.

Revision ID: 20260407_0006
Revises: c36115ec5636
Create Date: 2026-04-07 11:20:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260407_0006"
down_revision = "c36115ec5636"
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    return any(column["name"] == column_name for column in sa.inspect(bind).get_columns(table_name))


def upgrade() -> None:
    if not _column_exists("keywords", "match_scope"):
        op.add_column(
            "keywords",
            sa.Column(
                "match_scope",
                sa.String(length=32),
                nullable=True,
                server_default=sa.text("'title_content'"),
            ),
        )
    if not _column_exists("keywords", "equivalent_terms"):
        op.add_column(
            "keywords",
            sa.Column(
                "equivalent_terms",
                sa.JSON(),
                nullable=True,
                server_default=sa.text("'[]'"),
            ),
        )


def downgrade() -> None:
    op.drop_column("keywords", "equivalent_terms")
    op.drop_column("keywords", "match_scope")
