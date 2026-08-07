"""M4 product surface: versioned immutable Brief snapshots.

Revision ID: 20260807_0041
Revises: 20260730_0040
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260807_0041"
down_revision = "20260730_0040"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {row["name"] for row in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {row["name"] for row in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("brief_snapshots"):
        return
    columns = _columns("brief_snapshots")
    if "version" not in columns:
        with op.batch_alter_table("brief_snapshots") as batch:
            batch.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
        bind.execute(sa.text("UPDATE brief_snapshots SET version = 1 WHERE version IS NULL"))
    indexes = _indexes("brief_snapshots")
    if "idx_brief_period_type_unique" in indexes:
        op.drop_index("idx_brief_period_type_unique", table_name="brief_snapshots")
    if "idx_brief_period_type_version_unique" not in indexes:
        op.create_index(
            "idx_brief_period_type_version_unique",
            "brief_snapshots",
            ["period_key", "brief_type", "version"],
            unique=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("brief_snapshots"):
        return
    indexes = _indexes("brief_snapshots")
    if "idx_brief_period_type_version_unique" in indexes:
        op.drop_index("idx_brief_period_type_version_unique", table_name="brief_snapshots")
    if "idx_brief_period_type_unique" not in _indexes("brief_snapshots"):
        op.create_index(
            "idx_brief_period_type_unique",
            "brief_snapshots",
            ["period_key", "brief_type"],
            unique=True,
        )
