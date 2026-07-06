"""Add structured source fetch failure state columns.

Revision ID: 20260702_0022
Revises: 20260702_0021
Create Date: 2026-07-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260702_0022"
down_revision = "20260702_0021"
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(table_name):
        return False
    return any(column["name"] == column_name for column in sa.inspect(bind).get_columns(table_name))


def _add_column_once(column: sa.Column) -> None:
    if not _column_exists("sources", column.name):
        op.add_column("sources", column)


def _drop_column_once(column_name: str) -> None:
    if _column_exists("sources", column_name):
        op.drop_column("sources", column_name)


def upgrade() -> None:
    _add_column_once(sa.Column("fetch_failure_code", sa.String(length=64), nullable=True))
    _add_column_once(sa.Column("fetch_failure_status", sa.Integer(), nullable=True))
    _add_column_once(sa.Column("fetch_failure_severity", sa.String(length=16), nullable=True))
    _add_column_once(sa.Column("fetch_failure_retryable", sa.Boolean(), nullable=True))
    _add_column_once(sa.Column("fetch_failure_consecutive", sa.Integer(), nullable=True, server_default="0"))
    _add_column_once(sa.Column("fetch_failure_updated_at", sa.DateTime(), nullable=True))
    _add_column_once(sa.Column("fetch_cooldown_until", sa.DateTime(), nullable=True))


def downgrade() -> None:
    for column_name in (
        "fetch_cooldown_until",
        "fetch_failure_updated_at",
        "fetch_failure_consecutive",
        "fetch_failure_retryable",
        "fetch_failure_severity",
        "fetch_failure_status",
        "fetch_failure_code",
    ):
        _drop_column_once(column_name)
