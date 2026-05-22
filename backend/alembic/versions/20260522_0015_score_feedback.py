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


def upgrade() -> None:
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
    op.create_index("ix_score_feedback_content_id", "score_feedback", ["content_id"])
    op.create_index("ix_score_feedback_created_at", "score_feedback", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_score_feedback_created_at", table_name="score_feedback")
    op.drop_index("ix_score_feedback_content_id", table_name="score_feedback")
    op.drop_table("score_feedback")
