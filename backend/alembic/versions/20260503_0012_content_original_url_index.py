"""Add btree index on contents.original_url for URL-oriented queries.

Revision ID: 20260503_0012
Revises: 20260407_0011
Create Date: 2026-05-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260503_0012"
down_revision = "20260407_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    row = bind.execute(
        sa.text("SELECT 1 FROM sqlite_master WHERE type='index' AND name='ix_content_original_url' LIMIT 1")
    ).first()
    if row:
        return
    op.create_index("ix_content_original_url", "contents", ["original_url"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_content_original_url", table_name="contents")
