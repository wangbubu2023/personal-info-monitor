"""Add structured RSS health columns to sources.

Revision ID: 20260702_0023
Revises: 20260702_0022
Create Date: 2026-07-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260702_0023"
down_revision = "20260702_0022"
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
    _add_column_once(sa.Column("rss_health_status", sa.String(length=16), nullable=True))
    _add_column_once(sa.Column("rss_health_healthy", sa.Boolean(), nullable=True))
    _add_column_once(sa.Column("rss_health_item_count", sa.Integer(), nullable=True))
    _add_column_once(sa.Column("rss_health_last_update", sa.DateTime(), nullable=True))
    _add_column_once(sa.Column("rss_health_stale_days", sa.Integer(), nullable=True))
    _add_column_once(sa.Column("rss_health_reason", sa.String(length=64), nullable=True))
    _add_column_once(sa.Column("rss_health_checked_at", sa.DateTime(), nullable=True))
    _add_column_once(sa.Column("rss_health_feed_url", sa.Text(), nullable=True))


def downgrade() -> None:
    for column_name in (
        "rss_health_feed_url",
        "rss_health_checked_at",
        "rss_health_reason",
        "rss_health_stale_days",
        "rss_health_last_update",
        "rss_health_item_count",
        "rss_health_healthy",
        "rss_health_status",
    ):
        _drop_column_once(column_name)
