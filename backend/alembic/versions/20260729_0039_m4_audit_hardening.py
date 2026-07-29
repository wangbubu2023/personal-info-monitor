"""M4 audit hardening for Local Capture replay protection.

Revision ID: 20260729_0039
Revises: 20260724_0038
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260729_0039"
down_revision = "20260724_0038"
branch_labels = None
depends_on = None


def _indexes(table: str) -> set[str]:
    return {row["name"] for row in sa.inspect(op.get_bind()).get_indexes(table)}


def _columns(table: str) -> set[str]:
    return {row["name"] for row in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("local_capture_audits"):
        duplicate_summary = bind.execute(
            sa.text(
                """
                SELECT
                    COUNT(*) AS duplicate_group_count,
                    COALESCE(SUM(group_size), 0) AS duplicate_audit_count
                FROM (
                    SELECT task_token_hash, COUNT(*) AS group_size
                    FROM local_capture_audits
                    WHERE task_token_hash IS NOT NULL
                    GROUP BY task_token_hash
                    HAVING COUNT(*) > 1
                ) AS duplicate_tokens
                """
            )
        ).mappings().one()
        duplicate_group_count = int(duplicate_summary["duplicate_group_count"] or 0)
        duplicate_audit_count = int(duplicate_summary["duplicate_audit_count"] or 0)
        if duplicate_group_count:
            raise RuntimeError(
                "Cannot create Local Capture replay uniqueness index: "
                f"found {duplicate_group_count} duplicate task-token hash group(s) "
                f"across {duplicate_audit_count} immutable audit row(s); "
                "remediate explicitly without deleting audit evidence, then retry"
            )
        if "uq_local_capture_task_token_hash" not in _indexes("local_capture_audits"):
            op.create_index(
                "uq_local_capture_task_token_hash",
                "local_capture_audits",
                ["task_token_hash"],
                unique=True,
            )

    if inspector.has_table("brief_snapshots"):
        columns = _columns("brief_snapshots")
        with op.batch_alter_table("brief_snapshots") as batch:
            if "modality_violation_count" not in columns:
                batch.add_column(
                    sa.Column(
                        "modality_violation_count",
                        sa.Integer(),
                        nullable=False,
                        server_default="0",
                    )
                )
            if "publication_status" not in columns:
                batch.add_column(
                    sa.Column(
                        "publication_status",
                        sa.String(length=20),
                        nullable=False,
                        server_default="published",
                    )
                )
        bind.execute(
            sa.text(
                """
                UPDATE brief_snapshots
                SET modality_violation_count = CASE
                        WHEN modality_status = 'violation_flagged' THEN 1 ELSE 0 END,
                    publication_status = CASE
                        WHEN modality_status = 'violation_flagged' THEN 'blocked' ELSE 'published' END
                """
            )
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("brief_snapshots"):
        columns = _columns("brief_snapshots")
        with op.batch_alter_table("brief_snapshots") as batch:
            if "publication_status" in columns:
                batch.drop_column("publication_status")
            if "modality_violation_count" in columns:
                batch.drop_column("modality_violation_count")
    if inspector.has_table("local_capture_audits"):
        if "uq_local_capture_task_token_hash" in _indexes("local_capture_audits"):
            op.drop_index("uq_local_capture_task_token_hash", table_name="local_capture_audits")
