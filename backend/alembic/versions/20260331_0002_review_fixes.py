"""Add indexes for review-driven performance fixes.

Revision ID: 20260331_0002
Revises: 20260330_0001
Create Date: 2026-03-31 13:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260331_0002"
down_revision = "20260330_0001"
branch_labels = None
depends_on = None


def _index_exists(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    return any(index["name"] == index_name for index in sa.inspect(bind).get_indexes(table_name))


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str]) -> None:
    if not _index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns, unique=False)


def upgrade() -> None:
    _create_index_if_missing("ix_content_created_at", "contents", ["created_at"])
    _create_index_if_missing("ix_source_last_fetched_at", "sources", ["last_fetched_at"])
    _create_index_if_missing("ix_hourly_digest_date_hour", "hourly_digests", ["digest_date", "hour"])


def downgrade() -> None:
    op.drop_index("ix_hourly_digest_date_hour", table_name="hourly_digests")
    op.drop_index("ix_source_last_fetched_at", table_name="sources")
    op.drop_index("ix_content_created_at", table_name="contents")
