"""Add label and sharing metadata for auth configs.

Revision ID: 20260331_0003
Revises: 20260331_0002
Create Date: 2026-03-31 21:10:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260331_0003"
down_revision = "20260331_0002"
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    return any(column["name"] == column_name for column in sa.inspect(bind).get_columns(table_name))


def upgrade() -> None:
    if not _column_exists("auth_configs", "name"):
        op.add_column("auth_configs", sa.Column("name", sa.String(length=255), nullable=True))
    if not _column_exists("auth_configs", "is_shared"):
        op.add_column(
            "auth_configs",
            sa.Column("is_shared", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    op.drop_column("auth_configs", "is_shared")
    op.drop_column("auth_configs", "name")
