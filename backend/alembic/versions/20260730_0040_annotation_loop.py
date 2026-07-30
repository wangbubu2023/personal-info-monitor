"""Add the development annotation loop.

Revision ID: 20260730_0040
Revises: 20260729_0039
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260730_0040"
down_revision = "20260729_0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("annotation_tasks"):
        op.create_table(
            "annotation_tasks",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("task_type", sa.String(length=48), nullable=False),
            sa.Column("target_type", sa.String(length=24), nullable=False),
            sa.Column("target_id", sa.String(length=128), nullable=False),
            sa.Column("secondary_target_id", sa.String(length=128), nullable=True),
            sa.Column("target_fingerprint", sa.String(length=64), nullable=False),
            sa.Column("schema_version", sa.String(length=24), nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False),
            sa.Column("priority", sa.Float(), nullable=False),
            sa.Column("reason", sa.String(length=255), nullable=True),
            sa.Column("context_snapshot", sa.JSON(), nullable=False),
            sa.Column("prediction_snapshot", sa.JSON(), nullable=False),
            sa.Column("source_dataset", sa.String(length=128), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "task_type",
                "target_fingerprint",
                "schema_version",
                name="uq_annotation_task_fingerprint",
            ),
        )
        op.create_index(
            "ix_annotation_tasks_status_type",
            "annotation_tasks",
            ["status", "task_type"],
            unique=False,
        )
        op.create_index(
            "ix_annotation_tasks_target",
            "annotation_tasks",
            ["target_type", "target_id"],
            unique=False,
        )
    if not inspector.has_table("annotation_labels"):
        op.create_table(
            "annotation_labels",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("task_id", sa.String(length=36), nullable=False),
            sa.Column("annotator", sa.String(length=128), nullable=False),
            sa.Column("label_payload", sa.JSON(), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("supersedes_id", sa.String(length=36), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["supersedes_id"], ["annotation_labels.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["task_id"], ["annotation_tasks.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_annotation_labels_task_created",
            "annotation_labels",
            ["task_id", "created_at"],
            unique=False,
        )
        op.create_index("ix_annotation_labels_task_id", "annotation_labels", ["task_id"], unique=False)
    if not inspector.has_table("annotation_adjudications"):
        op.create_table(
            "annotation_adjudications",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("task_id", sa.String(length=36), nullable=False),
            sa.Column("final_payload", sa.JSON(), nullable=False),
            sa.Column("adjudicator", sa.String(length=128), nullable=False),
            sa.Column("rationale", sa.Text(), nullable=False),
            sa.Column("gold_candidate", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["task_id"], ["annotation_tasks.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("task_id", name="uq_annotation_adjudication_task"),
        )
        op.create_index(
            "ix_annotation_adjudications_task_id",
            "annotation_adjudications",
            ["task_id"],
            unique=False,
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("annotation_adjudications"):
        op.drop_table("annotation_adjudications")
    if inspector.has_table("annotation_labels"):
        op.drop_table("annotation_labels")
    if inspector.has_table("annotation_tasks"):
        op.drop_table("annotation_tasks")
