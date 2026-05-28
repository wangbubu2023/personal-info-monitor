"""Add btree indexes on contents.publish_time and contents.fetched_at for list ordering.

Revision ID: 20260401_0004
Revises: 20260331_0003
Create Date: 2026-04-01 12:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260401_0004"
down_revision = "20260331_0003"
branch_labels = None
depends_on = None


def _index_exists(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    return any(index["name"] == index_name for index in sa.inspect(bind).get_indexes(table_name))


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str]) -> None:
    if not _index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns, unique=False)


def upgrade() -> None:
    _create_index_if_missing("ix_content_publish_time", "contents", ["publish_time"])
    _create_index_if_missing("ix_content_fetched_at", "contents", ["fetched_at"])


def downgrade() -> None:
    op.drop_index("ix_content_fetched_at", table_name="contents")
    op.drop_index("ix_content_publish_time", table_name="contents")
