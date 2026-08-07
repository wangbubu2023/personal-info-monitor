"""M5A identity and rotating session persistence.

Revision ID: 20260807_0045
Revises: 20260807_0044
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.database import UUIDString


revision = "20260807_0045"
down_revision = "20260807_0044"
branch_labels = None
depends_on = None


def _table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not _table("identity_users"):
        op.create_table(
            "identity_users",
            sa.Column("id", UUIDString, primary_key=True),
            sa.Column("tenant_id", sa.String(128), nullable=False, server_default="default"),
            sa.Column("subject", sa.String(255), nullable=False),
            sa.Column("email", sa.String(320), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("uq_identity_user_tenant_subject", "identity_users", ["tenant_id", "subject"], unique=True)
    if not _table("identity_devices"):
        op.create_table(
            "identity_devices",
            sa.Column("id", UUIDString, primary_key=True),
            sa.Column("user_id", UUIDString, sa.ForeignKey("identity_users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("tenant_id", sa.String(128), nullable=False, server_default="default"),
            sa.Column("device_key", sa.String(128), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("last_seen_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_identity_devices_device_key", "identity_devices", ["device_key"], unique=True)
        op.create_index("ix_identity_device_tenant", "identity_devices", ["tenant_id", "status"])
    if not _table("service_principals"):
        op.create_table(
            "service_principals",
            sa.Column("id", UUIDString, primary_key=True),
            sa.Column("tenant_id", sa.String(128), nullable=False, server_default="default"),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("scopes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("uq_service_principal_tenant_name", "service_principals", ["tenant_id", "name"], unique=True)
    if not _table("identity_sessions"):
        op.create_table(
            "identity_sessions",
            sa.Column("id", UUIDString, primary_key=True),
            sa.Column("user_id", UUIDString, sa.ForeignKey("identity_users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("device_id", UUIDString, sa.ForeignKey("identity_devices.id", ondelete="CASCADE"), nullable=False),
            sa.Column("tenant_id", sa.String(128), nullable=False, server_default="default"),
            sa.Column("scopes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("access_token_hash", sa.String(128), nullable=False),
            sa.Column("access_expires_at", sa.DateTime(), nullable=False),
            sa.Column("refresh_family_id", sa.String(128), nullable=False),
            sa.Column("refresh_token_hash", sa.String(128), nullable=False),
            sa.Column("refresh_expires_at", sa.DateTime(), nullable=False),
            sa.Column("refresh_used_at", sa.DateTime(), nullable=True),
            sa.Column("rotated_from_id", UUIDString, nullable=True),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_identity_session_access_hash", "identity_sessions", ["access_token_hash"], unique=True)
        op.create_index("ix_identity_session_refresh_hash", "identity_sessions", ["refresh_token_hash"], unique=True)
        op.create_index("ix_identity_session_refresh_family", "identity_sessions", ["refresh_family_id"])
    if not _table("audit_actors"):
        op.create_table(
            "audit_actors",
            sa.Column("id", UUIDString, primary_key=True),
            sa.Column("tenant_id", sa.String(128), nullable=False, server_default="default"),
            sa.Column("actor_type", sa.String(32), nullable=False),
            sa.Column("actor_id", sa.String(128), nullable=False),
            sa.Column("action", sa.String(128), nullable=False),
            sa.Column("target_type", sa.String(64), nullable=True),
            sa.Column("target_id", sa.String(128), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    for name in ("audit_actors", "identity_sessions", "service_principals", "identity_devices", "identity_users"):
        if _table(name):
            op.drop_table(name)
