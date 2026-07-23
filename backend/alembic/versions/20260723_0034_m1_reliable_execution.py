"""M1 reliable execution, outbox, lineage, and Event migration scaffolding.

Revision ID: 20260723_0034
Revises: 20260722_0033
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.database import UUIDString

revision = "20260723_0034"
down_revision = "20260722_0033"
branch_labels = None
depends_on = None


def _table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _columns(table: str) -> set[str]:
    return {row["name"] for row in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {row["name"] for row in sa.inspect(op.get_bind()).get_indexes(table)}


def _add_columns(table: str, definitions: list[sa.Column]) -> None:
    existing = _columns(table)
    for column in definitions:
        if column.name not in existing:
            op.add_column(table, column)


def _index(name: str, table: str, columns: list[str]) -> None:
    if name not in _indexes(table):
        op.create_index(name, table, columns)


def _job_columns() -> list[sa.Column]:
    return [
        sa.Column("job_type", sa.String(32), nullable=False, server_default="fetch"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("payload_schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("deadline", sa.DateTime(), nullable=True),
        sa.Column("locked_by", sa.String(128), nullable=True),
        sa.Column("lease_token", sa.String(64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("abandoned_reason", sa.Text(), nullable=True),
    ]


def upgrade() -> None:
    _add_columns("fetch_jobs", _job_columns())
    _index("ix_fetch_jobs_dispatch", "fetch_jobs", ["state", "priority", "not_before"])
    _index("ix_fetch_jobs_lease", "fetch_jobs", ["state", "locked_by", "lease_token"])

    postprocess_columns = _job_columns()
    postprocess_columns[0] = sa.Column("job_type", sa.String(32), nullable=False, server_default="postprocess")
    postprocess_columns.extend(
        [
            sa.Column("trace_id", sa.String(64), nullable=False, server_default="migration"),
            sa.Column("pipeline_stage", sa.String(64), nullable=False, server_default="finish"),
            sa.Column("pipeline_version", sa.String(128), nullable=False, server_default="v1"),
        ]
    )
    _add_columns("postprocess_jobs", postprocess_columns)
    _index("ix_postprocess_jobs_dispatch", "postprocess_jobs", ["status", "priority", "run_after"])
    _index("ix_postprocess_jobs_lease", "postprocess_jobs", ["status", "locked_by", "lease_token"])

    if not _table("scheduler_runs"):
        op.create_table(
            "scheduler_runs",
            sa.Column("id", UUIDString(), nullable=False),
            sa.Column("schedule_id", sa.String(128), nullable=False),
            sa.Column("business_run_key", sa.String(256), nullable=False),
            sa.Column("scheduled_for", sa.DateTime(), nullable=False),
            sa.Column("policy_version", sa.String(32), nullable=False),
            sa.Column("state", sa.String(32), nullable=False),
            sa.Column("created_job_ids", sa.JSON(), nullable=False),
            sa.Column("misfire_reason", sa.String(128), nullable=True),
            sa.Column("catch_up_of", UUIDString(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("schedule_id", "business_run_key", name="uq_scheduler_business_run"),
        )
    _index("ix_scheduler_runs_state_scheduled", "scheduler_runs", ["state", "scheduled_for"])

    if not _table("outbox_events"):
        op.create_table(
            "outbox_events",
            sa.Column("id", UUIDString(), nullable=False),
            sa.Column("event_type", sa.String(64), nullable=False),
            sa.Column("aggregate_type", sa.String(64), nullable=False),
            sa.Column("aggregate_id", sa.String(128), nullable=False),
            sa.Column("payload_schema_version", sa.Integer(), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("idempotency_key", sa.String(512), nullable=False),
            sa.Column("state", sa.String(32), nullable=False),
            sa.Column("available_at", sa.DateTime(), nullable=False),
            sa.Column("attempt", sa.Integer(), nullable=False),
            sa.Column("max_attempts", sa.Integer(), nullable=False),
            sa.Column("locked_by", sa.String(128), nullable=True),
            sa.Column("lease_token", sa.String(64), nullable=True),
            sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("delivered_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("idempotency_key", name="uq_outbox_idempotency_key"),
        )
    _index("ix_outbox_dispatch", "outbox_events", ["state", "available_at"])

    if not _table("notification_deliveries"):
        op.create_table(
            "notification_deliveries",
            sa.Column("id", UUIDString(), nullable=False),
            sa.Column("outbox_id", UUIDString(), nullable=False),
            sa.Column("channel", sa.String(32), nullable=False),
            sa.Column("recipient_ref", sa.String(512), nullable=False),
            sa.Column("delivery_key", sa.String(512), nullable=False),
            sa.Column("provider", sa.String(64), nullable=False),
            sa.Column("state", sa.String(32), nullable=False),
            sa.Column("response_code", sa.Integer(), nullable=True),
            sa.Column("response_excerpt", sa.Text(), nullable=True),
            sa.Column("latency_ms", sa.Integer(), nullable=True),
            sa.Column("attempt", sa.Integer(), nullable=False),
            sa.Column("next_retry_at", sa.DateTime(), nullable=True),
            sa.Column("signature_key_version", sa.String(64), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("delivered_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["outbox_id"], ["outbox_events.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("delivery_key", name="uq_notification_delivery_key"),
        )
    _index("ix_notification_delivery_outbox", "notification_deliveries", ["outbox_id"])
    _index("ix_notification_delivery_state_retry", "notification_deliveries", ["state", "next_retry_at"])

    if not _table("lineage_edges"):
        op.create_table(
            "lineage_edges",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("from_type", sa.String(64), nullable=False),
            sa.Column("from_id", sa.String(128), nullable=False),
            sa.Column("to_type", sa.String(64), nullable=False),
            sa.Column("to_id", sa.String(128), nullable=False),
            sa.Column("relation", sa.String(64), nullable=False),
            sa.Column("pipeline_version", sa.String(128), nullable=True),
            sa.Column("trace_id", sa.String(64), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "from_type", "from_id", "to_type", "to_id", "relation",
                name="uq_lineage_edge",
            ),
        )
    _index("ix_lineage_from", "lineage_edges", ["from_type", "from_id"])
    _index("ix_lineage_to", "lineage_edges", ["to_type", "to_id"])
    _index("ix_lineage_trace", "lineage_edges", ["trace_id"])

    if not _table("event_aliases"):
        op.create_table(
            "event_aliases",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("canonical_event_id", sa.String(32), nullable=False),
            sa.Column("alias_type", sa.String(32), nullable=False),
            sa.Column("alias_value", sa.String(128), nullable=False),
            sa.Column("valid_from", sa.DateTime(), nullable=False),
            sa.Column("valid_to", sa.DateTime(), nullable=True),
            sa.Column("redirect_enabled", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["canonical_event_id"], ["content_events.event_id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("alias_type", "alias_value", name="uq_event_alias"),
        )
    _index("ix_event_alias_canonical", "event_aliases", ["canonical_event_id"])

    if not _table("event_operations"):
        op.create_table(
            "event_operations",
            sa.Column("id", UUIDString(), nullable=False),
            sa.Column("event_id", sa.String(32), nullable=False),
            sa.Column("operation_type", sa.String(32), nullable=False),
            sa.Column("input_event_ids", sa.JSON(), nullable=False),
            sa.Column("output_event_ids", sa.JSON(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("actor", sa.String(128), nullable=False),
            sa.Column("checkpoint", sa.String(128), nullable=True),
            sa.Column("checksum", sa.String(128), nullable=True),
            sa.Column("rollback_payload", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["event_id"], ["content_events.event_id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    _index("ix_event_operations_event_created", "event_operations", ["event_id", "created_at"])

    if not _table("event_memberships_v1"):
        op.create_table(
            "event_memberships_v1",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("event_id", sa.String(32), nullable=False),
            sa.Column("content_id", UUIDString(), nullable=False),
            sa.Column("assignment_version", sa.String(64), nullable=False),
            sa.Column("role", sa.String(32), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("explanation", sa.JSON(), nullable=False),
            sa.Column("shadow_only", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["event_id"], ["content_events.event_id"]),
            sa.ForeignKeyConstraint(["content_id"], ["contents.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("event_id", "content_id", "assignment_version", name="uq_event_membership_v1"),
        )
    _index("ix_event_memberships_v1_content", "event_memberships_v1", ["content_id"])


def downgrade() -> None:
    for table in (
        "event_memberships_v1",
        "event_operations",
        "event_aliases",
        "lineage_edges",
        "notification_deliveries",
        "outbox_events",
        "scheduler_runs",
    ):
        if _table(table):
            op.drop_table(table)

    for table, indexes in (
        ("postprocess_jobs", ["ix_postprocess_jobs_lease", "ix_postprocess_jobs_dispatch"]),
        ("fetch_jobs", ["ix_fetch_jobs_lease", "ix_fetch_jobs_dispatch"]),
    ):
        existing_indexes = _indexes(table)
        for name in indexes:
            if name in existing_indexes:
                op.drop_index(name, table_name=table)

    for table, names in (
        ("postprocess_jobs", [
            "pipeline_version", "pipeline_stage", "trace_id", "abandoned_reason",
            "heartbeat_at", "lease_expires_at", "lease_token", "locked_by",
            "deadline", "payload", "payload_schema_version", "priority", "job_type",
        ]),
        ("fetch_jobs", [
            "abandoned_reason", "heartbeat_at", "lease_expires_at", "lease_token",
            "locked_by", "deadline", "payload", "payload_schema_version", "priority", "job_type",
        ]),
    ):
        existing = _columns(table)
        for name in names:
            if name in existing:
                op.drop_column(table, name)
