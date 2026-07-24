"""M3 Event v1 stable kernel, snapshots, rebalance, and shadow audit.

Revision ID: 20260724_0037
Revises: 20260724_0036
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.database import UUIDString

revision = "20260724_0037"
down_revision = "20260724_0036"
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


def upgrade() -> None:
    _add_columns(
        "content_events",
        [
            sa.Column("anchor_signature", sa.String(64), nullable=True),
            sa.Column("cluster_version", sa.String(64), nullable=False, server_default="hybrid-v0"),
            sa.Column("latest_snapshot_version", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("event_state", sa.String(24), nullable=False, server_default="watch"),
            sa.Column("canonical_content_id", UUIDString(), nullable=True),
            sa.Column("centroid", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("dispersion", sa.Float(), nullable=False, server_default="0"),
            sa.Column("lifecycle_reason", sa.String(128), nullable=True),
            sa.Column("last_material_update_at", sa.DateTime(), nullable=True),
            sa.Column("last_rebalanced_at", sa.DateTime(), nullable=True),
        ],
    )
    _index("ix_content_events_cluster_status_update", "content_events", ["cluster_version", "status", "last_material_update_at"])

    _add_columns(
        "content_event_snapshots",
        [
            sa.Column("change_type", sa.String(32), nullable=False, server_default="added_fact"),
            sa.Column("change_fingerprint", sa.String(64), nullable=True),
            sa.Column("facts", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("evidence_refs", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("uncertainty", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("canonical_content_id", UUIDString(), nullable=True),
            sa.Column("generator_version", sa.String(64), nullable=False, server_default="snapshot-rules-v1"),
            sa.Column("explanation", sa.JSON(), nullable=False, server_default="{}"),
        ],
    )
    _index("ix_content_event_snapshots_fingerprint", "content_event_snapshots", ["event_id", "change_fingerprint"])

    _add_columns(
        "event_memberships_v1",
        [
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("assignment_method", sa.String(64), nullable=False, server_default="rules"),
            sa.Column("relation", sa.String(32), nullable=False, server_default="same_event"),
            sa.Column("effective_threshold", sa.Float(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        ],
    )
    op.execute("UPDATE event_memberships_v1 SET updated_at = created_at WHERE updated_at IS NULL")
    op.execute(
        """
        UPDATE event_memberships_v1
        SET active = 0
        WHERE active = 1
          AND id NOT IN (
              SELECT MAX(id)
              FROM event_memberships_v1
              WHERE active = 1
              GROUP BY content_id, assignment_version
          )
        """
    )
    _index("ix_event_memberships_v1_active_content", "event_memberships_v1", ["content_id", "active"])
    if "uq_event_memberships_v1_active_content_version" not in _indexes("event_memberships_v1"):
        op.create_index(
            "uq_event_memberships_v1_active_content_version",
            "event_memberships_v1",
            ["content_id", "assignment_version"],
            unique=True,
            sqlite_where=sa.text("active = 1"),
            postgresql_where=sa.text("active = true"),
        )

    if not _table("event_signatures"):
        op.create_table(
            "event_signatures",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("content_id", UUIDString(), nullable=False),
            sa.Column("signature_version", sa.String(64), nullable=False),
            sa.Column("normalized_entities", sa.JSON(), nullable=False),
            sa.Column("actors", sa.JSON(), nullable=False),
            sa.Column("trigger_action", sa.JSON(), nullable=False),
            sa.Column("object", sa.JSON(), nullable=False),
            sa.Column("location", sa.JSON(), nullable=False),
            sa.Column("event_time_start", sa.DateTime(), nullable=True),
            sa.Column("event_time_end", sa.DateTime(), nullable=True),
            sa.Column("event_time_precision", sa.String(16), nullable=True),
            sa.Column("quantities", sa.JSON(), nullable=False),
            sa.Column("identifiers", sa.JSON(), nullable=False),
            sa.Column("outcomes", sa.JSON(), nullable=False),
            sa.Column("modality", sa.String(24), nullable=False),
            sa.Column("source_claim_type", sa.String(32), nullable=False),
            sa.Column("language", sa.String(16), nullable=False),
            sa.Column("source_text", sa.JSON(), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("extraction_method", sa.String(32), nullable=False),
            sa.Column("model_version", sa.String(64), nullable=True),
            sa.Column("evidence_spans", sa.JSON(), nullable=False),
            sa.Column("fingerprint", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["content_id"], ["contents.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("content_id", "signature_version", name="uq_event_signature_content_version"),
        )
    _index("ix_event_signatures_identifiers", "event_signatures", ["signature_version", "created_at"])

    if not _table("event_assignment_logs"):
        op.create_table(
            "event_assignment_logs",
            sa.Column("id", UUIDString(), nullable=False),
            sa.Column("content_id", UUIDString(), nullable=False),
            sa.Column("assignment_version", sa.String(64), nullable=False),
            sa.Column("selected_event_id", sa.String(32), nullable=True),
            sa.Column("decision", sa.String(32), nullable=False),
            sa.Column("relation", sa.String(32), nullable=False),
            sa.Column("assignment_method", sa.String(64), nullable=False),
            sa.Column("candidate_count", sa.Integer(), nullable=False),
            sa.Column("candidates", sa.JSON(), nullable=False),
            sa.Column("component_scores", sa.JSON(), nullable=False),
            sa.Column("hard_conflicts", sa.JSON(), nullable=False),
            sa.Column("explain_reasons", sa.JSON(), nullable=False),
            sa.Column("effective_threshold", sa.Float(), nullable=True),
            sa.Column("latency_ms", sa.Float(), nullable=False),
            sa.Column("shadow_only", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["content_id"], ["contents.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["selected_event_id"], ["content_events.event_id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    _index("ix_event_assignment_logs_content_created", "event_assignment_logs", ["content_id", "created_at"])
    _index("ix_event_assignment_logs_event_created", "event_assignment_logs", ["selected_event_id", "created_at"])

    if not _table("event_rebalance_runs"):
        op.create_table(
            "event_rebalance_runs",
            sa.Column("id", UUIDString(), nullable=False),
            sa.Column("run_kind", sa.String(16), nullable=False),
            sa.Column("status", sa.String(24), nullable=False),
            sa.Column("config_version", sa.String(64), nullable=False),
            sa.Column("cursor", sa.String(128), nullable=True),
            sa.Column("scanned_event_count", sa.Integer(), nullable=False),
            sa.Column("candidate_pair_count", sa.Integer(), nullable=False),
            sa.Column("filtered_closed_count", sa.Integer(), nullable=False),
            sa.Column("checkpoint_count", sa.Integer(), nullable=False),
            sa.Column("wake_reasons", sa.JSON(), nullable=False),
            sa.Column("budgets", sa.JSON(), nullable=False),
            sa.Column("summary", sa.JSON(), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
    _index("ix_event_rebalance_runs_kind_created", "event_rebalance_runs", ["run_kind", "created_at"])

    if not _table("event_rebalance_suggestions"):
        op.create_table(
            "event_rebalance_suggestions",
            sa.Column("id", UUIDString(), nullable=False),
            sa.Column("run_id", UUIDString(), nullable=False),
            sa.Column("suggestion_type", sa.String(16), nullable=False),
            sa.Column("event_ids", sa.JSON(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("scores", sa.JSON(), nullable=False),
            sa.Column("evidence", sa.JSON(), nullable=False),
            sa.Column("fingerprint", sa.String(64), nullable=False),
            sa.Column("status", sa.String(24), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("reviewed_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["run_id"], ["event_rebalance_runs.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("suggestion_type", "fingerprint", name="uq_event_rebalance_suggestion"),
        )
    _index("ix_event_rebalance_suggestions_status", "event_rebalance_suggestions", ["status", "created_at"])

    if not _table("event_today_diff_audits"):
        op.create_table(
            "event_today_diff_audits",
            sa.Column("id", UUIDString(), nullable=False),
            sa.Column("audit_date", sa.String(10), nullable=False),
            sa.Column("v0_digest_fingerprint", sa.String(64), nullable=False),
            sa.Column("v1_fingerprint", sa.String(64), nullable=False),
            sa.Column("v0_items", sa.JSON(), nullable=False),
            sa.Column("v1_items", sa.JSON(), nullable=False),
            sa.Column("diff", sa.JSON(), nullable=False),
            sa.Column("assignment_version", sa.String(64), nullable=False),
            sa.Column("shadow_only", sa.Boolean(), nullable=False),
            sa.Column("production_affected", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("audit_date", "v0_digest_fingerprint", "v1_fingerprint", name="uq_event_today_diff"),
        )
    _index("ix_event_today_diff_audits_date", "event_today_diff_audits", ["audit_date", "created_at"])

    # Existing v0 rows stay isolated and resolvable. Do not attempt speculative
    # cross-event merges during schema migration.
    op.execute(
        """
        INSERT INTO event_aliases
            (canonical_event_id, alias_type, alias_value, valid_from, valid_to, redirect_enabled, created_at)
        SELECT event_id, 'legacy_event_id', event_id, created_at, NULL, 1, created_at
        FROM content_events
        WHERE NOT EXISTS (
            SELECT 1 FROM event_aliases a
            WHERE a.alias_type = 'legacy_event_id' AND a.alias_value = content_events.event_id
        )
        """
    )
    op.execute(
        """
        INSERT INTO event_aliases
            (canonical_event_id, alias_type, alias_value, valid_from, valid_to, redirect_enabled, created_at)
        SELECT event_id, 'event_key', event_key, created_at, NULL, 1, created_at
        FROM content_events
        WHERE NOT EXISTS (
            SELECT 1 FROM event_aliases a
            WHERE a.alias_type = 'event_key' AND a.alias_value = content_events.event_key
        )
        """
    )


def downgrade() -> None:
    for table in (
        "event_today_diff_audits",
        "event_rebalance_suggestions",
        "event_rebalance_runs",
        "event_assignment_logs",
        "event_signatures",
    ):
        if _table(table):
            op.drop_table(table)

    for table, index_names in (
        (
            "event_memberships_v1",
            [
                "uq_event_memberships_v1_active_content_version",
                "ix_event_memberships_v1_active_content",
            ],
        ),
        ("content_event_snapshots", ["ix_content_event_snapshots_fingerprint"]),
        ("content_events", ["ix_content_events_cluster_status_update"]),
    ):
        existing_indexes = _indexes(table)
        for name in index_names:
            if name in existing_indexes:
                op.drop_index(name, table_name=table)

    for table, names in (
        (
            "event_memberships_v1",
            ["updated_at", "effective_threshold", "relation", "assignment_method", "active"],
        ),
        (
            "content_event_snapshots",
            [
                "explanation",
                "generator_version",
                "canonical_content_id",
                "uncertainty",
                "evidence_refs",
                "facts",
                "change_fingerprint",
                "change_type",
            ],
        ),
        (
            "content_events",
            [
                "last_rebalanced_at",
                "last_material_update_at",
                "lifecycle_reason",
                "dispersion",
                "centroid",
                "canonical_content_id",
                "event_state",
                "latest_snapshot_version",
                "cluster_version",
                "anchor_signature",
            ],
        ),
    ):
        existing = _columns(table)
        removable = [name for name in names if name in existing]
        if op.get_bind().dialect.name == "sqlite" and removable:
            with op.batch_alter_table(table, recreate="always") as batch_op:
                for name in removable:
                    batch_op.drop_column(name)
        else:
            for name in removable:
                op.drop_column(table, name)
