"""Add btree indexes on contents.publish_time and contents.fetched_at for list ordering.

Revision ID: 20260401_0004
Revises: 20260331_0003
Create Date: 2026-04-01 12:00:00
"""

from __future__ import annotations

from alembic import op


# revision identifiers, used by Alembic.
revision = "20260401_0004"
down_revision = "20260331_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_content_publish_time", "contents", ["publish_time"], unique=False)
    op.create_index("ix_content_fetched_at", "contents", ["fetched_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_content_fetched_at", table_name="contents")
    op.drop_index("ix_content_publish_time", table_name="contents")
