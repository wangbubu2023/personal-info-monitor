"""Add personal monitor state tables.

Revision ID: 20260712_0031
Revises: 20260711_0029
Create Date: 2026-07-12 18:50:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260712_0031"
down_revision = "20260711_0029"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    return sa.inspect(bind).has_table(table_name)


def _index_exists(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    return any(index["name"] == index_name for index in sa.inspect(bind).get_indexes(table_name))


def _create_index_once(index_name: str, table_name: str, columns: list[str], *, unique: bool = False) -> None:
    if _table_exists(table_name) and not _index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def _drop_index_once(index_name: str, table_name: str) -> None:
    if _table_exists(table_name) and _index_exists(table_name, index_name):
        op.drop_index(index_name, table_name=table_name)


def _drop_table_once(table_name: str) -> None:
    if _table_exists(table_name):
        op.drop_table(table_name)


def upgrade() -> None:
    if not _table_exists("interaction_events"):
        op.create_table(
            "interaction_events",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("target_type", sa.String(length=16), nullable=False),
            sa.Column("target_id", sa.String(length=64), nullable=False),
            sa.Column("action", sa.String(length=32), nullable=False),
            sa.Column("action_value", sa.JSON(), nullable=True),
            sa.Column("content_id", sa.String(length=36), nullable=True),
            sa.Column("event_id", sa.String(length=32), nullable=True),
            sa.Column("event_version", sa.Integer(), nullable=True),
            sa.Column("source_id", sa.String(length=36), nullable=True),
            sa.Column("scope_type", sa.String(length=32), nullable=True),
            sa.Column("scope_key", sa.String(length=128), nullable=True),
            sa.Column("evidence", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_once("ix_interaction_events_target", "interaction_events", ["target_type", "target_id"])
    _create_index_once("ix_interaction_events_content", "interaction_events", ["content_id"])
    _create_index_once("ix_interaction_events_event", "interaction_events", ["event_id"])
    _create_index_once("ix_interaction_events_scope", "interaction_events", ["scope_type", "scope_key"])
    _create_index_once("ix_interaction_events_created", "interaction_events", ["created_at"])

    if not _table_exists("personal_item_states"):
        op.create_table(
            "personal_item_states",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("target_type", sa.String(length=16), nullable=False),
            sa.Column("target_id", sa.String(length=64), nullable=False),
            sa.Column("last_seen_version", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("saved", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("read_later", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("hidden", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("read_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("target_type", "target_id", name="uq_personal_item_state_target"),
        )
    _create_index_once("ix_personal_item_states_target", "personal_item_states", ["target_type", "target_id"])
    _create_index_once("ix_personal_item_states_updated", "personal_item_states", ["updated_at"])

    if not _table_exists("observation_aggregates"):
        op.create_table(
            "observation_aggregates",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("scope_type", sa.String(length=32), nullable=False),
            sa.Column("scope_key", sa.String(length=128), nullable=False),
            sa.Column("positive_evidence_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("negative_evidence_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("recent_activity_at", sa.DateTime(), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
            sa.Column("suggestion_status", sa.String(length=16), nullable=False, server_default="none"),
            sa.Column("suggested_rule", sa.String(length=16), nullable=True),
            sa.Column("evidence_summary", sa.Text(), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("scope_type", "scope_key", name="uq_observation_scope"),
        )
    _create_index_once("ix_observation_aggregates_scope", "observation_aggregates", ["scope_type", "scope_key"])
    _create_index_once("ix_observation_aggregates_status", "observation_aggregates", ["suggestion_status"])
    _create_index_once("ix_observation_aggregates_recent", "observation_aggregates", ["recent_activity_at"])

    if not _table_exists("user_rules"):
        op.create_table(
            "user_rules",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("scope_type", sa.String(length=32), nullable=False),
            sa.Column("scope_key", sa.String(length=128), nullable=False),
            sa.Column("rule", sa.String(length=16), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
            sa.Column("created_by", sa.String(length=32), nullable=False, server_default="user"),
            sa.Column("evidence_summary", sa.Text(), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_once("ix_user_rules_scope", "user_rules", ["scope_type", "scope_key"])
    _create_index_once("ix_user_rules_status", "user_rules", ["status"])
    _create_index_once("ix_user_rules_rule", "user_rules", ["rule"])


def downgrade() -> None:
    _drop_index_once("ix_user_rules_rule", "user_rules")
    _drop_index_once("ix_user_rules_status", "user_rules")
    _drop_index_once("ix_user_rules_scope", "user_rules")
    _drop_table_once("user_rules")
    _drop_index_once("ix_observation_aggregates_recent", "observation_aggregates")
    _drop_index_once("ix_observation_aggregates_status", "observation_aggregates")
    _drop_index_once("ix_observation_aggregates_scope", "observation_aggregates")
    _drop_table_once("observation_aggregates")
    _drop_index_once("ix_personal_item_states_updated", "personal_item_states")
    _drop_index_once("ix_personal_item_states_target", "personal_item_states")
    _drop_table_once("personal_item_states")
    _drop_index_once("ix_interaction_events_created", "interaction_events")
    _drop_index_once("ix_interaction_events_scope", "interaction_events")
    _drop_index_once("ix_interaction_events_event", "interaction_events")
    _drop_index_once("ix_interaction_events_content", "interaction_events")
    _drop_index_once("ix_interaction_events_target", "interaction_events")
    _drop_table_once("interaction_events")
