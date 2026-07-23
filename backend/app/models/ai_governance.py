"""Persistent AI governance records."""

from __future__ import annotations

import uuid

from sqlalchemy import Column, DateTime, Float, Index, Integer, JSON, String, Text, UniqueConstraint

from app.database import Base, UUIDString
from app.utils.datetime import utcnow_naive


class AiSubjectiveScoreCache(Base):
    """Business-idempotent cache for shadow subjective scoring."""

    __tablename__ = "ai_subjective_score_cache"
    __table_args__ = (
        UniqueConstraint("cache_key", name="uq_ai_subjective_score_cache_key"),
        Index("ix_ai_subjective_score_cache_content", "content_id", "created_at"),
        Index("ix_ai_subjective_score_cache_state", "state", "created_at"),
    )

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    cache_key = Column(String(64), nullable=False)
    content_id = Column(UUIDString, nullable=True)
    input_hash = Column(String(64), nullable=False)
    input_scope = Column(String(32), nullable=False)
    provider = Column(String(64), nullable=False)
    model = Column(String(255), nullable=False)
    model_version = Column(String(320), nullable=False)
    prompt_version = Column(String(64), nullable=False)
    score = Column(Float, nullable=True)
    rationale = Column(Text, nullable=True)
    token_estimate = Column(Integer, nullable=False, default=0)
    actual_usage = Column(JSON, nullable=True)
    estimated_cost = Column(Float, nullable=False, default=0.0)
    state = Column(String(32), nullable=False, default="ready")
    failure_code = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)
    expires_at = Column(DateTime, nullable=True)
    last_hit_at = Column(DateTime, nullable=True)
    hit_count = Column(Integer, nullable=False, default=0)


class AiPolicyMigrationState(Base):
    """Proof that legacy environment policy was persisted exactly once."""

    __tablename__ = "ai_policy_migration_state"

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    migration_version = Column(Integer, nullable=False, unique=True)
    migrated_at = Column(DateTime, nullable=False, default=utcnow_naive)
    source_legacy_keys_present = Column(JSON, nullable=False, default=list)
    before_values = Column(JSON, nullable=False, default=dict)
    resolved_product_settings = Column(JSON, nullable=False, default=dict)
    warnings_emitted = Column(JSON, nullable=False, default=list)
    actor = Column(String(64), nullable=False, default="startup")
    build_version = Column(String(64), nullable=False, default="m1a")


__all__ = ["AiPolicyMigrationState", "AiSubjectiveScoreCache"]
