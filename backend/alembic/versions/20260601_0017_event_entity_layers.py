"""L3 event clusters/summaries + L5 knowledge entity layer.

Revision ID: 20260601_0017
Revises: 20260601_0016
Create Date: 2026-06-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260601_0017"
down_revision = "20260601_0016"
branch_labels = None
depends_on = None


def _table_exists(bind, name: str) -> bool:
    return bool(
        bind.execute(
            sa.text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:name LIMIT 1"),
            {"name": name},
        ).first()
    )


def upgrade() -> None:
    bind = op.get_bind()

    if not _table_exists(bind, "event_clusters"):
        op.create_table(
            "event_clusters",
            sa.Column("event_id", sa.String(length=32), primary_key=True, nullable=False),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("domain", sa.String(length=32), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
            sa.Column("first_seen_at", sa.DateTime(), nullable=True),
            sa.Column("last_seen_at", sa.DateTime(), nullable=True),
            sa.Column("canonical_summary", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_event_clusters_domain", "event_clusters", ["domain"])
        op.create_index("ix_event_clusters_status", "event_clusters", ["status"])

    if not _table_exists(bind, "event_cluster_atoms"):
        op.create_table(
            "event_cluster_atoms",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "event_id",
                sa.String(length=32),
                sa.ForeignKey("event_clusters.event_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("atom_id", sa.String(length=32), nullable=False),
            sa.Column("role", sa.String(length=16), nullable=False, server_default="background"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("event_id", "atom_id", name="uq_event_cluster_atom"),
        )
        op.create_index("ix_event_cluster_atoms_event_id", "event_cluster_atoms", ["event_id"])
        op.create_index("ix_event_cluster_atoms_atom_id", "event_cluster_atoms", ["atom_id"])

    if not _table_exists(bind, "event_summaries"):
        op.create_table(
            "event_summaries",
            sa.Column("summary_id", sa.String(length=32), primary_key=True, nullable=False),
            sa.Column(
                "event_id",
                sa.String(length=32),
                sa.ForeignKey("event_clusters.event_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("window_start", sa.DateTime(), nullable=True),
            sa.Column("window_end", sa.DateTime(), nullable=True),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("model", sa.String(length=128), nullable=True),
            sa.Column("source_atom_ids", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_event_summaries_event_id", "event_summaries", ["event_id"])

    if not _table_exists(bind, "knowledge_entities"):
        op.create_table(
            "knowledge_entities",
            sa.Column("entity_id", sa.String(length=32), primary_key=True, nullable=False),
            sa.Column("canonical_name", sa.String(length=255), nullable=False),
            sa.Column("entity_type", sa.String(length=32), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_knowledge_entities_canonical_name", "knowledge_entities", ["canonical_name"])
        op.create_index("ix_knowledge_entities_entity_type", "knowledge_entities", ["entity_type"])

    if not _table_exists(bind, "entity_aliases"):
        op.create_table(
            "entity_aliases",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("alias", sa.String(length=255), nullable=False),
            sa.Column(
                "entity_id",
                sa.String(length=32),
                sa.ForeignKey("knowledge_entities.entity_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("source", sa.String(length=64), nullable=True),
            sa.UniqueConstraint("alias", "entity_id", name="uq_entity_alias"),
        )
        op.create_index("ix_entity_aliases_alias", "entity_aliases", ["alias"])
        op.create_index("ix_entity_aliases_entity_id", "entity_aliases", ["entity_id"])

    if not _table_exists(bind, "atom_entities"):
        op.create_table(
            "atom_entities",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("atom_id", sa.String(length=32), nullable=False),
            sa.Column(
                "entity_id",
                sa.String(length=32),
                sa.ForeignKey("knowledge_entities.entity_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("role", sa.String(length=32), nullable=True),
            sa.UniqueConstraint("atom_id", "entity_id", "role", name="uq_atom_entity_role"),
        )
        op.create_index("ix_atom_entities_atom_id", "atom_entities", ["atom_id"])
        op.create_index("ix_atom_entities_entity_id", "atom_entities", ["entity_id"])

    if not _table_exists(bind, "entity_relations"):
        op.create_table(
            "entity_relations",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("subject_entity_id", sa.String(length=32), nullable=False),
            sa.Column("relation_type", sa.String(length=32), nullable=False),
            sa.Column("object_entity_id", sa.String(length=32), nullable=False),
            sa.Column("evidence_atom_id", sa.String(length=32), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=False, server_default="0.7"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_entity_relations_subject_entity_id", "entity_relations", ["subject_entity_id"])
        op.create_index("ix_entity_relations_object_entity_id", "entity_relations", ["object_entity_id"])


def downgrade() -> None:
    bind = op.get_bind()
    for table in (
        "entity_relations",
        "atom_entities",
        "entity_aliases",
        "knowledge_entities",
        "event_summaries",
        "event_cluster_atoms",
        "event_clusters",
    ):
        if _table_exists(bind, table):
            op.drop_table(table)
