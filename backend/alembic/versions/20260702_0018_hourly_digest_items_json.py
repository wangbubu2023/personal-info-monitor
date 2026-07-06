"""Add structured hourly digest event item snapshots.

Revision ID: 20260702_0018
Revises: 20260601_0017
Create Date: 2026-07-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260702_0018"
down_revision = "20260601_0017"
branch_labels = None
depends_on = None


def _columns(bind, table: str) -> set[str]:
    rows = bind.execute(sa.text(f"PRAGMA table_info('{table}')")).fetchall()
    return {row[1] for row in rows}


def upgrade() -> None:
    bind = op.get_bind()
    if "items_json" not in _columns(bind, "hourly_digests"):
        op.add_column(
            "hourly_digests",
            sa.Column("items_json", sa.JSON(), nullable=False, server_default="[]"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "items_json" in _columns(bind, "hourly_digests"):
        with op.batch_alter_table("hourly_digests") as batch:
            batch.drop_column("items_json")
