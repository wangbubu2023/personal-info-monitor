"""M5B normalized Source state compatibility tables.

Revision ID: 20260807_0043
Revises: 20260807_0042
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.database import UUIDString


revision = "20260807_0043"
down_revision = "20260807_0042"
branch_labels = None
depends_on = None


def _table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not _table("source_fetch_state"):
        op.create_table(
            "source_fetch_state",
            sa.Column("id", UUIDString, primary_key=True),
            sa.Column("source_id", UUIDString, sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
            sa.Column("last_fetched_at", sa.DateTime(), nullable=True),
            sa.Column("last_content_id", sa.String(255), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failure_code", sa.String(64), nullable=True),
            sa.Column("failure_status", sa.Integer(), nullable=True),
            sa.Column("failure_severity", sa.String(16), nullable=True),
            sa.Column("cooldown_until", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("uq_source_fetch_state_source", "source_fetch_state", ["source_id"], unique=True)
    if not _table("source_discovery_stats"):
        op.create_table(
            "source_discovery_stats",
            sa.Column("id", UUIDString, primary_key=True),
            sa.Column("source_id", UUIDString, sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
            sa.Column("checked_at", sa.DateTime(), nullable=True),
            sa.Column("total", sa.Integer(), nullable=True),
            sa.Column("kept", sa.Integer(), nullable=True),
            sa.Column("dropped", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("pagination", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("uq_source_discovery_stats_source", "source_discovery_stats", ["source_id"], unique=True)
    if not _table("source_session_state"):
        op.create_table(
            "source_session_state",
            sa.Column("id", UUIDString, primary_key=True),
            sa.Column("source_id", UUIDString, sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
            sa.Column("status", sa.String(16), nullable=True),
            sa.Column("reason", sa.String(64), nullable=True),
            sa.Column("suggested_action", sa.String(64), nullable=True),
            sa.Column("validated_at", sa.DateTime(), nullable=True),
            sa.Column("details", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("alert_reason", sa.String(64), nullable=True),
            sa.Column("alert_sent_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("uq_source_session_state_source", "source_session_state", ["source_id"], unique=True)
    if not _table("source_policy"):
        op.create_table(
            "source_policy",
            sa.Column("id", UUIDString, primary_key=True),
            sa.Column("source_id", UUIDString, sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("fetch_interval", sa.Integer(), nullable=False, server_default="60"),
            sa.Column("use_keyword_filter", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("auth_required", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("policy_version", sa.String(32), nullable=False, server_default="source-policy-v1"),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("uq_source_policy_source", "source_policy", ["source_id"], unique=True)


def downgrade() -> None:
    for name in ("source_policy", "source_session_state", "source_discovery_stats", "source_fetch_state"):
        if _table(name):
            op.drop_table(name)
