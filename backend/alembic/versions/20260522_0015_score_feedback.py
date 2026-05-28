"""Add score_feedback table for score lab calibration.

Revision ID: 20260522_0015
Revises: 20260520_0014
Create Date: 2026-05-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260522_0015"
down_revision = "20260520_0014"
branch_labels = None
depends_on = None


def _table_exists(bind, name: str) -> bool:
    return bool(
        bind.execute(
            sa.text(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=:name LIMIT 1"
            ),
            {"name": name},
        ).first()
    )


def _index_exists(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    return any(index["name"] == index_name for index in sa.inspect(bind).get_indexes(table_name))


def _create_score_feedback_indexes_if_missing() -> None:
    if not _index_exists("score_feedback", "ix_score_feedback_content_id"):
        op.create_index("ix_score_feedback_content_id", "score_feedback", ["content_id"])
    if not _index_exists("score_feedback", "ix_score_feedback_created_at"):
        op.create_index("ix_score_feedback_created_at", "score_feedback", ["created_at"])


def upgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "score_feedback"):
        _create_score_feedback_indexes_if_missing()
        return

    op.create_table(
        "score_feedback",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("content_id", sa.String(length=36), sa.ForeignKey("contents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("expected_status", sa.String(length=16), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    _create_score_feedback_indexes_if_missing()


def downgrade() -> None:
    op.drop_index("ix_score_feedback_created_at", table_name="score_feedback")
    op.drop_index("ix_score_feedback_content_id", table_name="score_feedback")
    op.drop_table("score_feedback")
