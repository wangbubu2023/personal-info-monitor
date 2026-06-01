"""Atom lifecycle state machine + operation log.

Adds status/evolution columns to ``atoms`` and creates ``atom_operations`` so the
atom library becomes auditable instead of an extraction-result table.

Revision ID: 20260601_0016
Revises: 20260522_0015
Create Date: 2026-06-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260601_0016"
down_revision = "20260522_0015"
branch_labels = None
depends_on = None


def _table_exists(bind, name: str) -> bool:
    return bool(
        bind.execute(
            sa.text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:name LIMIT 1"),
            {"name": name},
        ).first()
    )


def _columns(bind, table: str) -> set[str]:
    rows = bind.execute(sa.text(f"PRAGMA table_info('{table}')")).fetchall()
    return {row[1] for row in rows}


def _new_columns() -> list[sa.Column]:
    return [
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("is_latest", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("supersedes_atom_id", sa.String(length=32), nullable=True),
        sa.Column("superseded_by_atom_id", sa.String(length=32), nullable=True),
        sa.Column("reconcile_group_id", sa.String(length=64), nullable=True),
        sa.Column("canonical_text", sa.Text(), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("quality_flags", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("evidence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("extraction_run_id", sa.String(length=64), nullable=True),
        sa.Column("reconcile_reason", sa.Text(), nullable=True),
    ]


def upgrade() -> None:
    bind = op.get_bind()

    if _table_exists(bind, "atoms"):
        existing = _columns(bind, "atoms")
        for column in _new_columns():
            if column.name not in existing:
                op.add_column("atoms", column)
        indexes = {
            row[0]
            for row in bind.execute(
                sa.text("SELECT name FROM sqlite_master WHERE type='index'")
            )
        }
        if "ix_atoms_status" not in indexes:
            op.create_index("ix_atoms_status", "atoms", ["status"])
        if "ix_atoms_is_latest" not in indexes:
            op.create_index("ix_atoms_is_latest", "atoms", ["is_latest"])
        if "ix_atoms_reconcile_group_id" not in indexes:
            op.create_index("ix_atoms_reconcile_group_id", "atoms", ["reconcile_group_id"])

    if not _table_exists(bind, "atom_operations"):
        op.create_table(
            "atom_operations",
            sa.Column("operation_id", sa.String(length=32), primary_key=True, nullable=False),
            sa.Column("operation_type", sa.String(length=16), nullable=False),
            sa.Column("content_id", sa.String(length=36), nullable=True),
            sa.Column("atom_id", sa.String(length=32), nullable=True),
            sa.Column("related_atom_ids", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("model_provider", sa.String(length=64), nullable=True),
            sa.Column("model_name", sa.String(length=128), nullable=True),
            sa.Column("prompt", sa.Text(), nullable=True),
            sa.Column("raw_response", sa.Text(), nullable=True),
            sa.Column("parsed", sa.JSON(), nullable=True),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("quality_flags", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_atom_operations_operation_type", "atom_operations", ["operation_type"])
        op.create_index("ix_atom_operations_content_id", "atom_operations", ["content_id"])
        op.create_index("ix_atom_operations_atom_id", "atom_operations", ["atom_id"])


def downgrade() -> None:
    bind = op.get_bind()

    if _table_exists(bind, "atom_operations"):
        op.drop_index("ix_atom_operations_atom_id", table_name="atom_operations")
        op.drop_index("ix_atom_operations_content_id", table_name="atom_operations")
        op.drop_index("ix_atom_operations_operation_type", table_name="atom_operations")
        op.drop_table("atom_operations")

    if _table_exists(bind, "atoms"):
        indexes = {
            row[0]
            for row in bind.execute(
                sa.text("SELECT name FROM sqlite_master WHERE type='index'")
            )
        }
        for index in ("ix_atoms_reconcile_group_id", "ix_atoms_is_latest", "ix_atoms_status"):
            if index in indexes:
                op.drop_index(index, table_name="atoms")
        with op.batch_alter_table("atoms") as batch:
            for column in reversed(_new_columns()):
                batch.drop_column(column.name)
