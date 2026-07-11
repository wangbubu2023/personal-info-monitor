"""Add stable content event tables.

Revision ID: 20260711_0029
Revises: 20260710_0030
Create Date: 2026-07-11 08:35:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260711_0029"
down_revision = "20260710_0030"
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
    if not _table_exists("content_events"):
        op.create_table(
            "content_events",
            sa.Column("event_id", sa.String(length=32), nullable=False),
            sa.Column("event_key", sa.String(length=128), nullable=False),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("first_seen_at", sa.DateTime(), nullable=True),
            sa.Column("last_seen_at", sa.DateTime(), nullable=True),
            sa.Column("importance_score", sa.Float(), nullable=True),
            sa.Column("incremental_score", sa.Float(), nullable=True),
            sa.Column("confidence_score", sa.Float(), nullable=True),
            sa.Column("independent_source_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("source_names", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("event_id"),
            sa.UniqueConstraint("event_key", name="uq_content_events_event_key"),
        )
    _create_index_once("ix_content_events_event_key", "content_events", ["event_key"])
    _create_index_once("ix_content_events_last_seen", "content_events", ["last_seen_at"])
    _create_index_once("ix_content_events_status", "content_events", ["status"])

    if not _table_exists("content_event_memberships"):
        op.create_table(
            "content_event_memberships",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("event_id", sa.String(length=32), nullable=False),
            sa.Column("content_id", sa.String(length=36), nullable=False),
            sa.Column("role", sa.String(length=24), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("evidence", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["content_id"], ["contents.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["event_id"], ["content_events.event_id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("event_id", "content_id", name="uq_content_event_membership"),
        )
    _create_index_once("ix_content_event_memberships_event", "content_event_memberships", ["event_id"])
    _create_index_once("ix_content_event_memberships_content", "content_event_memberships", ["content_id"])

    if not _table_exists("content_event_snapshots"):
        op.create_table(
            "content_event_snapshots",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("event_id", sa.String(length=32), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("what_changed", sa.Text(), nullable=True),
            sa.Column("why_matters", sa.Text(), nullable=True),
            sa.Column("source_content_ids", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["event_id"], ["content_events.event_id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("event_id", "version", name="uq_content_event_snapshot_version"),
        )
    _create_index_once("ix_content_event_snapshots_event", "content_event_snapshots", ["event_id"])


def downgrade() -> None:
    _drop_index_once("ix_content_event_snapshots_event", "content_event_snapshots")
    _drop_table_once("content_event_snapshots")
    _drop_index_once("ix_content_event_memberships_content", "content_event_memberships")
    _drop_index_once("ix_content_event_memberships_event", "content_event_memberships")
    _drop_table_once("content_event_memberships")
    _drop_index_once("ix_content_events_status", "content_events")
    _drop_index_once("ix_content_events_last_seen", "content_events")
    _drop_index_once("ix_content_events_event_key", "content_events")
    _drop_table_once("content_events")
