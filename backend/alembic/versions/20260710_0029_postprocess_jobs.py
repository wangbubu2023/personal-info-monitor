"""Add durable postprocess jobs.

Revision ID: 20260710_0029
Revises: 20260709_0028
Create Date: 2026-07-10 19:18:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260710_0029"
down_revision = "20260709_0028"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    return sa.inspect(bind).has_table(table_name)


def _index_exists(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    return any(index["name"] == index_name for index in sa.inspect(bind).get_indexes(table_name))


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(table_name):
        return False
    return any(column["name"] == column_name for column in sa.inspect(bind).get_columns(table_name))


def _add_column_once(table_name: str, column: sa.Column) -> None:
    if _table_exists(table_name) and not _column_exists(table_name, column.name):
        op.add_column(table_name, column)


def _drop_column_once(table_name: str, column_name: str) -> None:
    if _column_exists(table_name, column_name):
        op.drop_column(table_name, column_name)


def _create_index_once(index_name: str, table_name: str, columns: list[str], *, unique: bool = False) -> None:
    if _table_exists(table_name) and not _index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def _drop_index_once(index_name: str, table_name: str) -> None:
    if _table_exists(table_name) and _index_exists(table_name, index_name):
        op.drop_index(index_name, table_name=table_name)


def upgrade() -> None:
    if not _table_exists("postprocess_jobs"):
        op.create_table(
            "postprocess_jobs",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("idempotency_key", sa.String(length=512), nullable=False),
            sa.Column("content_id", sa.String(length=36), nullable=False),
            sa.Column("job_id", sa.String(length=128), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False),
            sa.Column("max_attempts", sa.Integer(), nullable=False),
            sa.Column("run_after", sa.DateTime(), nullable=False),
            sa.Column("locked_at", sa.DateTime(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("failure_code", sa.String(length=64), nullable=True),
            sa.Column("failure_severity", sa.String(length=16), nullable=True),
            sa.Column("failure_retryable", sa.Boolean(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("idempotency_key", name="uq_postprocess_jobs_idempotency_key"),
        )
    _add_column_once("postprocess_jobs", sa.Column("failure_code", sa.String(length=64), nullable=True))
    _add_column_once("postprocess_jobs", sa.Column("failure_severity", sa.String(length=16), nullable=True))
    _add_column_once("postprocess_jobs", sa.Column("failure_retryable", sa.Boolean(), nullable=True))
    _create_index_once(
        "ix_postprocess_jobs_status_run_after",
        "postprocess_jobs",
        ["status", "run_after"],
    )
    _create_index_once("ix_postprocess_jobs_content_id", "postprocess_jobs", ["content_id"])


def downgrade() -> None:
    _drop_index_once("ix_postprocess_jobs_content_id", "postprocess_jobs")
    _drop_index_once("ix_postprocess_jobs_status_run_after", "postprocess_jobs")
    for column_name in ("failure_retryable", "failure_severity", "failure_code"):
        _drop_column_once("postprocess_jobs", column_name)
    if _table_exists("postprocess_jobs"):
        op.drop_table("postprocess_jobs")
