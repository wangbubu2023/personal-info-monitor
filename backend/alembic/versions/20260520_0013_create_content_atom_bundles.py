"""Create content_atom_bundles table (Phase 6 — optional atoms layer).

Revision ID: 20260520_0013
Revises: 20260503_0012
Create Date: 2026-05-20

Adds the storage for the optional ``atoms`` layer (events / entities /
relations per Content row). The table is created unconditionally so the
migration stays linear, but the atoms feature itself is gated by the
``ATOMS_ENABLED`` flag — when the flag is off the table simply stays
empty and no code path reads or writes it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260520_0013"
down_revision = "20260503_0012"
branch_labels = None
depends_on = None


def _table_exists(bind, name: str) -> bool:
    return bool(
        bind.execute(
            sa.text(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=:name LIMIT 1"
            ),
            {"name": name},
        ).first()
    )


def upgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "content_atom_bundles"):
        return

    op.create_table(
        "content_atom_bundles",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column(
            "content_id",
            sa.String(length=36),
            sa.ForeignKey("contents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("schema_version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("events", sa.JSON, nullable=False),
        sa.Column("entities", sa.JSON, nullable=False),
        sa.Column("relations", sa.JSON, nullable=False),
        sa.Column("bundle_metadata", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("content_id", name="uq_content_atom_bundle_content_id"),
    )
    op.create_index(
        "ix_content_atom_bundles_content_id",
        "content_atom_bundles",
        ["content_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_content_atom_bundles_content_id", table_name="content_atom_bundles")
    op.drop_table("content_atom_bundles")
