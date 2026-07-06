"""Add structured last-fetch outcome columns to sources.

Revision ID: 20260702_0025
Revises: 20260702_0024
Create Date: 2026-07-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260702_0025"
down_revision = "20260702_0024"
branch_labels = None
depends_on = None


def _column_exists(column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(column["name"] == column_name for column in inspector.get_columns("sources"))


def _add_column_once(column: sa.Column) -> None:
    if not _column_exists(column.name):
        op.add_column("sources", column)


def _drop_column_once(column_name: str) -> None:
    if _column_exists(column_name):
        op.drop_column("sources", column_name)


def upgrade() -> None:
    _add_column_once(sa.Column("last_fetch_outcome_code", sa.String(length=64), nullable=True))
    _add_column_once(sa.Column("last_fetch_outcome_severity", sa.String(length=16), nullable=True))
    _add_column_once(sa.Column("last_fetch_outcome_message", sa.Text(), nullable=True))
    _add_column_once(sa.Column("last_fetch_outcome_updated_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    for column_name in (
        "last_fetch_outcome_updated_at",
        "last_fetch_outcome_message",
        "last_fetch_outcome_severity",
        "last_fetch_outcome_code",
    ):
        _drop_column_once(column_name)
