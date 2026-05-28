"""Keyword manual equivalent terms and auto-merge toggle.

Revision ID: 20260407_0009
Revises: 20260407_0008
Create Date: 2026-04-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260407_0009"
down_revision = "20260407_0008"
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    return any(column["name"] == column_name for column in sa.inspect(bind).get_columns(table_name))


def upgrade() -> None:
    if not _column_exists("keywords", "manual_equivalent_terms"):
        op.add_column(
            "keywords",
            sa.Column(
                "manual_equivalent_terms",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            ),
        )
    if not _column_exists("keywords", "include_auto_equivalent_terms"):
        op.add_column(
            "keywords",
            sa.Column(
                "include_auto_equivalent_terms",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("1"),
            ),
        )


def downgrade() -> None:
    op.drop_column("keywords", "include_auto_equivalent_terms")
    op.drop_column("keywords", "manual_equivalent_terms")
