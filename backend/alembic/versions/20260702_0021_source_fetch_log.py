"""Create source fetch log table.

Revision ID: 20260702_0021
Revises: 20260702_0020
Create Date: 2026-07-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260702_0021"
down_revision = "20260702_0020"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    return sa.inspect(bind).has_table(table_name)


def _index_exists(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    if not _table_exists(table_name):
        return False
    return any(index["name"] == index_name for index in sa.inspect(bind).get_indexes(table_name))


def upgrade() -> None:
    if not _table_exists("source_fetch_log"):
        op.create_table(
            "source_fetch_log",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("source_id", sa.String(length=36), nullable=False),
            sa.Column("attempted_at", sa.DateTime(), nullable=False),
            sa.Column("outcome", sa.String(length=16), nullable=False),
            sa.Column("severity", sa.String(length=16), nullable=True),
            sa.Column("failure_code", sa.String(length=64), nullable=True),
            sa.Column("saved_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("latency_ms", sa.Integer(), nullable=True),
            sa.Column("fulltext_ok", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("fulltext_total", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("preferred_strategy", sa.String(length=64), nullable=True),
            sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    if not _index_exists("source_fetch_log", "ix_source_fetch_log_attempted_at"):
        op.create_index("ix_source_fetch_log_attempted_at", "source_fetch_log", ["attempted_at"])
    if not _index_exists("source_fetch_log", "ix_source_fetch_log_outcome"):
        op.create_index("ix_source_fetch_log_outcome", "source_fetch_log", ["outcome"])
    if not _index_exists("source_fetch_log", "ix_source_fetch_log_source_attempted"):
        op.create_index(
            "ix_source_fetch_log_source_attempted",
            "source_fetch_log",
            ["source_id", "attempted_at"],
        )


def downgrade() -> None:
    if not _table_exists("source_fetch_log"):
        return
    if _index_exists("source_fetch_log", "ix_source_fetch_log_source_attempted"):
        op.drop_index("ix_source_fetch_log_source_attempted", table_name="source_fetch_log")
    if _index_exists("source_fetch_log", "ix_source_fetch_log_outcome"):
        op.drop_index("ix_source_fetch_log_outcome", table_name="source_fetch_log")
    if _index_exists("source_fetch_log", "ix_source_fetch_log_attempted_at"):
        op.drop_index("ix_source_fetch_log_attempted_at", table_name="source_fetch_log")
    op.drop_table("source_fetch_log")
