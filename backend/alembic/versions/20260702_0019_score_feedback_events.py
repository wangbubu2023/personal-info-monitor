"""Add event fields to score feedback.

Revision ID: 20260702_0019
Revises: 20260702_0018
Create Date: 2026-07-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260702_0019"
down_revision = "20260702_0018"
branch_labels = None
depends_on = None


def _columns(bind, table: str) -> set[str]:
    rows = bind.execute(sa.text(f"PRAGMA table_info('{table}')")).fetchall()
    return {row[1] for row in rows}


def _index_exists(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    return any(index["name"] == index_name for index in sa.inspect(bind).get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    columns = _columns(bind, "score_feedback")
    if "event_type" not in columns:
        op.add_column("score_feedback", sa.Column("event_type", sa.String(length=32), nullable=True))
    if "event_value" not in columns:
        op.add_column("score_feedback", sa.Column("event_value", sa.JSON(), nullable=True))
    if not _index_exists("score_feedback", "ix_score_feedback_event_type"):
        op.create_index("ix_score_feedback_event_type", "score_feedback", ["event_type"])


def downgrade() -> None:
    bind = op.get_bind()
    columns = _columns(bind, "score_feedback")
    if _index_exists("score_feedback", "ix_score_feedback_event_type"):
        op.drop_index("ix_score_feedback_event_type", table_name="score_feedback")
    with op.batch_alter_table("score_feedback") as batch:
        if "event_value" in columns:
            batch.drop_column("event_value")
        if "event_type" in columns:
            batch.drop_column("event_type")
