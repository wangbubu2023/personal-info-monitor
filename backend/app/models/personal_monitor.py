"""Personal monitor state models.

These tables keep user-owned reading state separate from general scoring. Natural
interactions are append-only observations; only explicit ``UserRule`` rows can
change highlight/quiet/notify behavior.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Column, DateTime, Float, Index, Integer, JSON, String, Text, UniqueConstraint

from app.database import Base, UUIDString
from app.utils.datetime import utcnow_naive


class InteractionEvent(Base):
    """Append-only ledger of natural user actions."""

    __tablename__ = "interaction_events"
    __table_args__ = (
        Index("ix_interaction_events_target", "target_type", "target_id"),
        Index("ix_interaction_events_content", "content_id"),
        Index("ix_interaction_events_event", "event_id"),
        Index("ix_interaction_events_scope", "scope_type", "scope_key"),
        Index("ix_interaction_events_created", "created_at"),
    )

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    target_type = Column(String(16), nullable=False)
    target_id = Column(String(64), nullable=False)
    action = Column(String(32), nullable=False)
    action_value = Column(JSON, nullable=True)
    content_id = Column(UUIDString, nullable=True)
    event_id = Column(String(32), nullable=True)
    event_version = Column(Integer, nullable=True)
    source_id = Column(UUIDString, nullable=True)
    scope_type = Column(String(32), nullable=True)
    scope_key = Column(String(128), nullable=True)
    evidence = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)


class PersonalItemState(Base):
    """Current user state for a report or event."""

    __tablename__ = "personal_item_states"
    __table_args__ = (
        UniqueConstraint("target_type", "target_id", name="uq_personal_item_state_target"),
        Index("ix_personal_item_states_target", "target_type", "target_id"),
        Index("ix_personal_item_states_updated", "updated_at"),
    )

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    target_type = Column(String(16), nullable=False)
    target_id = Column(String(64), nullable=False)
    last_seen_version = Column(Integer, nullable=False, default=0)
    saved = Column(Boolean, nullable=False, default=False)
    read_later = Column(Boolean, nullable=False, default=False)
    hidden = Column(Boolean, nullable=False, default=False)
    read_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)
    updated_at = Column(DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)


class ObservationAggregate(Base):
    """Aggregated evidence for suggesting explicit rules."""

    __tablename__ = "observation_aggregates"
    __table_args__ = (
        UniqueConstraint("scope_type", "scope_key", name="uq_observation_scope"),
        Index("ix_observation_aggregates_scope", "scope_type", "scope_key"),
        Index("ix_observation_aggregates_status", "suggestion_status"),
        Index("ix_observation_aggregates_recent", "recent_activity_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    scope_type = Column(String(32), nullable=False)
    scope_key = Column(String(128), nullable=False)
    positive_evidence_count = Column(Integer, nullable=False, default=0)
    negative_evidence_count = Column(Integer, nullable=False, default=0)
    recent_activity_at = Column(DateTime, nullable=True)
    confidence = Column(Float, nullable=False, default=0.0)
    suggestion_status = Column(String(16), nullable=False, default="none")
    suggested_rule = Column(String(16), nullable=True)
    evidence_summary = Column(Text, nullable=True)
    metadata_ = Column("metadata", JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)
    updated_at = Column(DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)


class UserRule(Base):
    """Explicit user-confirmed monitor rule."""

    __tablename__ = "user_rules"
    __table_args__ = (
        Index("ix_user_rules_scope", "scope_type", "scope_key"),
        Index("ix_user_rules_status", "status"),
        Index("ix_user_rules_rule", "rule"),
    )

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    scope_type = Column(String(32), nullable=False)
    scope_key = Column(String(128), nullable=False)
    rule = Column(String(16), nullable=False)
    status = Column(String(16), nullable=False, default="active")
    created_by = Column(String(32), nullable=False, default="user")
    evidence_summary = Column(Text, nullable=True)
    metadata_ = Column("metadata", JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)
    updated_at = Column(DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)
