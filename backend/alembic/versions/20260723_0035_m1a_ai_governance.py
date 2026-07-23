"""M1A subjective-score cache and one-time AI policy migration state.

Revision ID: 20260723_0035
Revises: 20260723_0034
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.database import UUIDString

revision = "20260723_0035"
down_revision = "20260723_0034"
branch_labels = None
depends_on = None


def _table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not _table("ai_subjective_score_cache"):
        op.create_table(
            "ai_subjective_score_cache",
            sa.Column("id", UUIDString(), nullable=False),
            sa.Column("cache_key", sa.String(64), nullable=False),
            sa.Column("content_id", UUIDString(), nullable=True),
            sa.Column("input_hash", sa.String(64), nullable=False),
            sa.Column("input_scope", sa.String(32), nullable=False),
            sa.Column("provider", sa.String(64), nullable=False),
            sa.Column("model", sa.String(255), nullable=False),
            sa.Column("model_version", sa.String(320), nullable=False),
            sa.Column("prompt_version", sa.String(64), nullable=False),
            sa.Column("score", sa.Float(), nullable=True),
            sa.Column("rationale", sa.Text(), nullable=True),
            sa.Column("token_estimate", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("actual_usage", sa.JSON(), nullable=True),
            sa.Column("estimated_cost", sa.Float(), nullable=False, server_default="0"),
            sa.Column("state", sa.String(32), nullable=False, server_default="ready"),
            sa.Column("failure_code", sa.String(64), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("last_hit_at", sa.DateTime(), nullable=True),
            sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("cache_key", name="uq_ai_subjective_score_cache_key"),
        )
        op.create_index(
            "ix_ai_subjective_score_cache_content",
            "ai_subjective_score_cache",
            ["content_id", "created_at"],
        )
        op.create_index(
            "ix_ai_subjective_score_cache_state",
            "ai_subjective_score_cache",
            ["state", "created_at"],
        )

    if not _table("ai_policy_migration_state"):
        op.create_table(
            "ai_policy_migration_state",
            sa.Column("id", UUIDString(), nullable=False),
            sa.Column("migration_version", sa.Integer(), nullable=False),
            sa.Column("migrated_at", sa.DateTime(), nullable=False),
            sa.Column("source_legacy_keys_present", sa.JSON(), nullable=False),
            sa.Column("before_values", sa.JSON(), nullable=False),
            sa.Column("resolved_product_settings", sa.JSON(), nullable=False),
            sa.Column("warnings_emitted", sa.JSON(), nullable=False),
            sa.Column("actor", sa.String(64), nullable=False),
            sa.Column("build_version", sa.String(64), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("migration_version"),
        )


def downgrade() -> None:
    op.drop_table("ai_policy_migration_state")
    op.drop_index("ix_ai_subjective_score_cache_state", table_name="ai_subjective_score_cache")
    op.drop_index("ix_ai_subjective_score_cache_content", table_name="ai_subjective_score_cache")
    op.drop_table("ai_subjective_score_cache")
