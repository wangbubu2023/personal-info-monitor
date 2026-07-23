"""M0 durable FetchJob and one-time Web sessions.

Revision ID: 20260722_0033
Revises: 20260713_0032
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.database import UUIDString

revision = "20260722_0033"
down_revision = "20260713_0032"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _create_index_once(name: str, table: str, columns: list[str], *, unique: bool = False) -> None:
    existing = {row["name"] for row in sa.inspect(op.get_bind()).get_indexes(table)}
    if name not in existing:
        op.create_index(name, table, columns, unique=unique)


def upgrade() -> None:
    if not _has_table("fetch_jobs"):
        op.create_table(
            "fetch_jobs",
            sa.Column("id", UUIDString(), nullable=False),
            sa.Column("business_key", sa.String(length=512), nullable=False),
            sa.Column("trace_id", sa.String(length=64), nullable=False),
            sa.Column("source_id", UUIDString(), nullable=False),
            sa.Column("fetch_kind", sa.String(length=32), nullable=False),
            sa.Column("due_window", sa.DateTime(), nullable=False),
            sa.Column("state", sa.String(length=32), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False),
            sa.Column("max_attempts", sa.Integer(), nullable=False),
            sa.Column("not_before", sa.DateTime(), nullable=False),
            sa.Column("enqueued_at", sa.DateTime(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("failure_code", sa.String(length=64), nullable=True),
            sa.Column("failure_message", sa.Text(), nullable=True),
            sa.Column("failure_retryable", sa.Boolean(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("business_key", name="uq_fetch_jobs_business_key"),
        )
    _create_index_once("ix_fetch_jobs_source_id", "fetch_jobs", ["source_id"])
    _create_index_once("ix_fetch_jobs_state_not_before", "fetch_jobs", ["state", "not_before"])

    if not _has_table("bootstrap_codes"):
        op.create_table(
            "bootstrap_codes",
            sa.Column("id", UUIDString(), nullable=False),
            sa.Column("code_hash", sa.String(length=64), nullable=False),
            sa.Column("actor", sa.String(length=128), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("used_at", sa.DateTime(), nullable=True),
            sa.Column("revoked", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_once("ix_bootstrap_codes_hash", "bootstrap_codes", ["code_hash"], unique=True)

    if not _has_table("web_sessions"):
        op.create_table(
            "web_sessions",
            sa.Column("id", UUIDString(), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("actor", sa.String(length=128), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(), nullable=False),
            sa.Column("idle_expires_at", sa.DateTime(), nullable=False),
            sa.Column("absolute_expires_at", sa.DateTime(), nullable=False),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("rotated_from_id", UUIDString(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_once("ix_web_sessions_token_hash", "web_sessions", ["token_hash"], unique=True)
    _create_index_once("ix_web_sessions_expires", "web_sessions", ["revoked_at", "absolute_expires_at"])


def downgrade() -> None:
    if _has_table("web_sessions"):
        op.drop_table("web_sessions")
    if _has_table("bootstrap_codes"):
        op.drop_table("bootstrap_codes")
    if _has_table("fetch_jobs"):
        op.drop_table("fetch_jobs")
