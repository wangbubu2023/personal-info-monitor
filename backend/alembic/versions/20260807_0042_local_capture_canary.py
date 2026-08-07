"""Persist Local Capture ingest linkage and source health snapshots.

Revision ID: 20260807_0042
Revises: 20260807_0041
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.database import UUIDString


revision = "20260807_0042"
down_revision = "20260807_0041"
branch_labels = None
depends_on = None


def _table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _columns(name: str) -> set[str]:
    return {row["name"] for row in sa.inspect(op.get_bind()).get_columns(name)}


def upgrade() -> None:
    if _table("local_capture_audits"):
        columns = _columns("local_capture_audits")
        with op.batch_alter_table("local_capture_audits") as batch:
            if "source_id" not in columns:
                batch.add_column(sa.Column("source_id", UUIDString, nullable=True))
            if "content_id" not in columns:
                batch.add_column(sa.Column("content_id", UUIDString, nullable=True))
            if "ingest_status" not in columns:
                batch.add_column(sa.Column("ingest_status", sa.String(32), nullable=False, server_default="captured"))
    if not _table("source_health_snapshots"):
        op.create_table(
            "source_health_snapshots",
            sa.Column("id", UUIDString, primary_key=True),
            sa.Column("source_id", UUIDString, sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
            sa.Column("check_type", sa.String(32), nullable=False, server_default="daily_canary"),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("http_status", sa.Integer(), nullable=True),
            sa.Column("body_length", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("login_required", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("paywall_residual_detected", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("selector_quality", sa.Float(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("observed_at", sa.DateTime(), nullable=False),
        )
        op.create_index(
            "idx_source_health_source_observed",
            "source_health_snapshots",
            ["source_id", "observed_at"],
        )


def downgrade() -> None:
    if _table("source_health_snapshots"):
        op.drop_table("source_health_snapshots")
    if _table("local_capture_audits"):
        columns = _columns("local_capture_audits")
        with op.batch_alter_table("local_capture_audits") as batch:
            for name in ("ingest_status", "content_id", "source_id"):
                if name in columns:
                    batch.drop_column(name)
