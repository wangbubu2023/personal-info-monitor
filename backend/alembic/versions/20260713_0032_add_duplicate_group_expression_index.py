"""Add an expression index for legacy duplicate-group visibility queries.

Revision ID: 20260713_0032
Revises: 20260712_0031
Create Date: 2026-07-13 15:20:00
"""

from __future__ import annotations

from alembic import op


revision = "20260713_0032"
down_revision = "20260712_0031"
branch_labels = None
depends_on = None

_INDEX_NAME = "ix_contents_dup_group_id"


def upgrade() -> None:
    # SQLite expression indexes have been available since 3.9.0. PIM's
    # supported Python/SQLite runtimes are newer; IF NOT EXISTS also makes the
    # migration safe for operators who applied the field workaround manually.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_contents_dup_group_id "
        "ON contents(json_extract(metadata, '$.duplicate_group_id'))"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_INDEX_NAME}")
