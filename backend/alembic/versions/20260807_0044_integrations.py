"""M5B WebSub and Webhook integration persistence.

Revision ID: 20260807_0044
Revises: 20260807_0043
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.database import UUIDString


revision = "20260807_0044"
down_revision = "20260807_0043"
branch_labels = None
depends_on = None


def _table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not _table("websub_subscriptions"):
        op.create_table(
            "websub_subscriptions",
            sa.Column("id", UUIDString, primary_key=True),
            sa.Column("source_id", UUIDString, sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
            sa.Column("hub_url", sa.Text(), nullable=False),
            sa.Column("topic_url", sa.Text(), nullable=False),
            sa.Column("callback_path", sa.String(255), nullable=False),
            sa.Column("verify_token_hash", sa.String(128), nullable=False),
            sa.Column("secret_encrypted", sa.Text(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
            sa.Column("last_verified_at", sa.DateTime(), nullable=True),
            sa.Column("last_event_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("uq_websub_source_topic", "websub_subscriptions", ["source_id", "topic_url"], unique=True)
    if not _table("websub_deliveries"):
        op.create_table(
            "websub_deliveries",
            sa.Column("id", UUIDString, primary_key=True),
            sa.Column("subscription_id", UUIDString, sa.ForeignKey("websub_subscriptions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("event_hash", sa.String(128), nullable=False),
            sa.Column("payload_checksum", sa.String(128), nullable=False),
            sa.Column("item_count", sa.String(16), nullable=False, server_default="0"),
            sa.Column("status", sa.String(20), nullable=False, server_default="accepted"),
            sa.Column("fetch_job_id", UUIDString, nullable=True),
            sa.Column("received_at", sa.DateTime(), nullable=False),
        )
        op.create_index("uq_websub_delivery_event_hash", "websub_deliveries", ["event_hash"], unique=True)
    if not _table("webhook_subscriptions"):
        op.create_table(
            "webhook_subscriptions",
            sa.Column("id", UUIDString, primary_key=True),
            sa.Column("target_url", sa.Text(), nullable=False),
            sa.Column("event_filters", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("secret_encrypted", sa.Text(), nullable=False),
            sa.Column("secret_key_version", sa.String(32), nullable=False, server_default="v1"),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("uq_webhook_target", "webhook_subscriptions", ["target_url"], unique=True)


def downgrade() -> None:
    for name in ("webhook_subscriptions", "websub_deliveries", "websub_subscriptions"):
        if _table(name):
            op.drop_table(name)
