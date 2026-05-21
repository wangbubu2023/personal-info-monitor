"""Normalize atoms storage: atoms + atom_relations; drop content_atom_bundles.

Revision ID: 20260520_0014
Revises: 20260520_0013
Create Date: 2026-05-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260520_0014"
down_revision = "20260520_0013"
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

    if not _table_exists(bind, "atoms"):
        op.create_table(
            "atoms",
            sa.Column("atom_id", sa.String(length=32), primary_key=True, nullable=False),
            sa.Column(
                "content_id",
                sa.String(length=36),
                sa.ForeignKey("contents.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("atom_type", sa.String(length=16), nullable=False),
            sa.Column("domain", sa.String(length=32), nullable=False),
            sa.Column("source_sentence", sa.Text(), nullable=False),
            sa.Column("source_url", sa.Text(), nullable=False),
            sa.Column("atom_source", sa.String(length=255), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("source_credibility", sa.Float(), nullable=False),
            sa.Column("fact_confidence", sa.Float(), nullable=False),
            sa.Column("schema_version", sa.Integer(), nullable=False, server_default="2"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "content_id",
                "source_sentence",
                "atom_type",
                name="uq_atom_content_sentence_type",
            ),
        )
        op.create_index("ix_atoms_content_id", "atoms", ["content_id"])
        op.create_index("ix_atoms_atom_type", "atoms", ["atom_type"])
        op.create_index("ix_atoms_domain", "atoms", ["domain"])
        op.create_index("ix_atoms_verified", "atoms", ["verified"])

    if not _table_exists(bind, "atom_relations"):
        op.create_table(
            "atom_relations",
            sa.Column("rel_id", sa.String(length=32), primary_key=True, nullable=False),
            sa.Column(
                "atom_a",
                sa.String(length=32),
                sa.ForeignKey("atoms.atom_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "atom_b",
                sa.String(length=32),
                sa.ForeignKey("atoms.atom_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("relation_type", sa.String(length=16), nullable=False),
            sa.Column("direction", sa.String(length=8), nullable=False),
            sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("fact_confidence", sa.Float(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("atom_a", "atom_b", name="uq_atom_relation_pair"),
        )
        op.create_index("ix_atom_relations_atom_a", "atom_relations", ["atom_a"])
        op.create_index("ix_atom_relations_atom_b", "atom_relations", ["atom_b"])

    if not _table_exists(bind, "atom_id_sequences"):
        op.create_table(
            "atom_id_sequences",
            sa.Column("prefix", sa.String(length=16), primary_key=True, nullable=False),
            sa.Column("last_seq", sa.Integer(), nullable=False, server_default="0"),
        )

    if _table_exists(bind, "content_atom_bundles"):
        op.drop_index("ix_content_atom_bundles_content_id", table_name="content_atom_bundles")
        op.drop_table("content_atom_bundles")


def downgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "atom_relations"):
        op.drop_index("ix_atom_relations_atom_b", table_name="atom_relations")
        op.drop_index("ix_atom_relations_atom_a", table_name="atom_relations")
        op.drop_table("atom_relations")
    if _table_exists(bind, "atoms"):
        op.drop_index("ix_atoms_verified", table_name="atoms")
        op.drop_index("ix_atoms_domain", table_name="atoms")
        op.drop_index("ix_atoms_atom_type", table_name="atoms")
        op.drop_index("ix_atoms_content_id", table_name="atoms")
        op.drop_table("atoms")
    if _table_exists(bind, "atom_id_sequences"):
        op.drop_table("atom_id_sequences")

    if not _table_exists(bind, "content_atom_bundles"):
        op.create_table(
            "content_atom_bundles",
            sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
            sa.Column(
                "content_id",
                sa.String(length=36),
                sa.ForeignKey("contents.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("events", sa.JSON(), nullable=False),
            sa.Column("entities", sa.JSON(), nullable=False),
            sa.Column("relations", sa.JSON(), nullable=False),
            sa.Column("bundle_metadata", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("content_id", name="uq_content_atom_bundle_content_id"),
        )
        op.create_index(
            "ix_content_atom_bundles_content_id",
            "content_atom_bundles",
            ["content_id"],
        )
