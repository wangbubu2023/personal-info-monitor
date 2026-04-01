"""Add indexes for review-driven performance fixes.

Revision ID: 20260331_0002
Revises: 20260330_0001
Create Date: 2026-03-31 13:30:00
"""

from __future__ import annotations

from alembic import op


# revision identifiers, used by Alembic.
revision = "20260331_0002"
down_revision = "20260330_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_content_created_at", "contents", ["created_at"], unique=False)
    op.create_index("ix_source_last_fetched_at", "sources", ["last_fetched_at"], unique=False)
    op.create_index("ix_hourly_digest_date_hour", "hourly_digests", ["digest_date", "hour"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_hourly_digest_date_hour", table_name="hourly_digests")
    op.drop_index("ix_source_last_fetched_at", table_name="sources")
    op.drop_index("ix_content_created_at", table_name="contents")
