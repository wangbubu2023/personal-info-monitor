"""Add use_keyword_filter column to sources table.

Revision ID: 20260401_0005
Revises: 20260401_0004
Create Date: 2026-04-01 12:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260401_0005"
down_revision = "20260401_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column("use_keyword_filter", sa.Boolean(), nullable=True, server_default=sa.text("0")),
    )


def downgrade() -> None:
    op.drop_column("sources", "use_keyword_filter")
