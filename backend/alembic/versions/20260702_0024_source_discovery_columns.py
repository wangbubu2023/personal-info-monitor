"""Add structured listing-discovery diagnostic columns to sources.

Revision ID: 20260702_0024
Revises: 20260702_0023
Create Date: 2026-07-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260702_0024"
down_revision = "20260702_0023"
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
    _add_column_once(sa.Column("discovery_checked_at", sa.DateTime(), nullable=True))
    for column_name in (
        "discovery_total",
        "discovery_kept",
        "discovery_dropped_no_url",
        "discovery_dropped_off_domain",
        "discovery_dropped_deny",
        "discovery_dropped_allow_miss",
        "discovery_dropped_non_article_url",
        "discovery_dropped_short_title",
        "discovery_dropped_duplicate",
        "discovery_dropped_stale",
        "discovery_truncated",
        "discovery_listing_urls_configured",
        "discovery_listing_pages_total",
        "discovery_listing_pages_fetched",
        "discovery_listing_pages_failed",
        "discovery_pagination_max_pages",
    ):
        _add_column_once(sa.Column(column_name, sa.Integer(), nullable=True))


def downgrade() -> None:
    for column_name in (
        "discovery_pagination_max_pages",
        "discovery_listing_pages_failed",
        "discovery_listing_pages_fetched",
        "discovery_listing_pages_total",
        "discovery_listing_urls_configured",
        "discovery_truncated",
        "discovery_dropped_stale",
        "discovery_dropped_duplicate",
        "discovery_dropped_short_title",
        "discovery_dropped_non_article_url",
        "discovery_dropped_allow_miss",
        "discovery_dropped_deny",
        "discovery_dropped_off_domain",
        "discovery_dropped_no_url",
        "discovery_kept",
        "discovery_total",
        "discovery_checked_at",
    ):
        _drop_column_once(column_name)
