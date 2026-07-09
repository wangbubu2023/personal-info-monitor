"""Add Auth Assistant pairing tables.

Revision ID: 20260709_0028
Revises: 20260708_0027
Create Date: 2026-07-09 19:35:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260709_0028"
down_revision = "20260708_0027"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    return sa.inspect(bind).has_table(table_name)


def _index_exists(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    return any(index["name"] == index_name for index in sa.inspect(bind).get_indexes(table_name))


def _create_index_once(index_name: str, table_name: str, columns: list[str], *, unique: bool = False) -> None:
    if _table_exists(table_name) and not _index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def _drop_index_once(index_name: str, table_name: str) -> None:
    if _table_exists(table_name) and _index_exists(table_name, index_name):
        op.drop_index(index_name, table_name=table_name)


def _drop_table_once(table_name: str) -> None:
    if _table_exists(table_name):
        op.drop_table(table_name)


def upgrade() -> None:
    if not _table_exists("auth_assistant_pairing_tokens"):
        op.create_table(
            "auth_assistant_pairing_tokens",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("token_hash", sa.String(length=128), nullable=False),
            sa.Column("token_hint", sa.String(length=32), nullable=False),
            sa.Column(
                "status",
                sa.Enum("PENDING", "CLAIMED", "EXPIRED", "REVOKED", name="authassistanttokenstatus"),
                nullable=False,
            ),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("claimed_at", sa.DateTime(), nullable=True),
            sa.Column("device_id", sa.String(length=36), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_once(
        op.f("ix_auth_assistant_pairing_tokens_token_hash"),
        "auth_assistant_pairing_tokens",
        ["token_hash"],
        unique=True,
    )

    if not _table_exists("auth_assistant_devices"):
        op.create_table(
            "auth_assistant_devices",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("token_hash", sa.String(length=128), nullable=False),
            sa.Column("status", sa.Enum("ACTIVE", "REVOKED", name="authassistantdevicestatus"), nullable=False),
            sa.Column("app_version", sa.String(length=64), nullable=True),
            sa.Column("last_seen_at", sa.DateTime(), nullable=True),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("capabilities", sa.JSON(), nullable=False),
            sa.Column("metadata", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_once(
        op.f("ix_auth_assistant_devices_token_hash"),
        "auth_assistant_devices",
        ["token_hash"],
        unique=True,
    )

    if not _table_exists("auth_assistant_import_logs"):
        op.create_table(
            "auth_assistant_import_logs",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("device_id", sa.String(length=36), nullable=True),
            sa.Column("site_host", sa.String(length=255), nullable=True),
            sa.Column("profile_count", sa.String(length=32), nullable=False),
            sa.Column("result", sa.JSON(), nullable=False),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_once(
        op.f("ix_auth_assistant_import_logs_device_id"),
        "auth_assistant_import_logs",
        ["device_id"],
        unique=False,
    )


def downgrade() -> None:
    _drop_index_once(op.f("ix_auth_assistant_import_logs_device_id"), "auth_assistant_import_logs")
    _drop_table_once("auth_assistant_import_logs")
    _drop_index_once(op.f("ix_auth_assistant_devices_token_hash"), "auth_assistant_devices")
    _drop_table_once("auth_assistant_devices")
    _drop_index_once(op.f("ix_auth_assistant_pairing_tokens_token_hash"), "auth_assistant_pairing_tokens")
    _drop_table_once("auth_assistant_pairing_tokens")
