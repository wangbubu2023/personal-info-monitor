"""M2 explicit quality feedback adjudication.

Revision ID: 20260724_0036
Revises: 20260723_0035
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.database import UUIDString

revision = "20260724_0036"
down_revision = "20260723_0035"
branch_labels = None
depends_on = None


def _table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if _table("quality_adjudications"):
        return
    op.create_table(
        "quality_adjudications",
        sa.Column("id", UUIDString(), nullable=False),
        sa.Column("feedback_id", UUIDString(), nullable=False),
        sa.Column("issue_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="adjudicated"),
        sa.Column("verdict", sa.String(24), nullable=False),
        sa.Column("adjudicator", sa.String(128), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("gold_candidate", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("hard_negative", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["feedback_id"], ["score_feedback.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("feedback_id", name="uq_quality_adjudication_feedback"),
    )
    op.create_index("ix_quality_adjudications_feedback_id", "quality_adjudications", ["feedback_id"])
    op.create_index(
        "ix_quality_adjudications_issue_status",
        "quality_adjudications",
        ["issue_type", "status"],
    )
    op.create_index("ix_quality_adjudications_created_at", "quality_adjudications", ["created_at"])


def downgrade() -> None:
    if not _table("quality_adjudications"):
        return
    op.drop_index("ix_quality_adjudications_created_at", table_name="quality_adjudications")
    op.drop_index("ix_quality_adjudications_issue_status", table_name="quality_adjudications")
    op.drop_index("ix_quality_adjudications_feedback_id", table_name="quality_adjudications")
    op.drop_table("quality_adjudications")
