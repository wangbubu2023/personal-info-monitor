"""Event v1 signatures, diagnostics, rebalance, and shadow audit records."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint

from app.database import Base, UUIDString
from app.utils.datetime import utcnow_naive


class EventSignature(Base):
    __tablename__ = "event_signatures"
    __table_args__ = (
        UniqueConstraint("content_id", "signature_version", name="uq_event_signature_content_version"),
        Index("ix_event_signatures_identifiers", "signature_version", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    content_id = Column(UUIDString, ForeignKey("contents.id", ondelete="CASCADE"), nullable=False)
    signature_version = Column(String(64), nullable=False, default="event-signature-v1")
    normalized_entities = Column(JSON, nullable=False, default=list)
    actors = Column(JSON, nullable=False, default=list)
    trigger_action = Column(JSON, nullable=False, default=dict)
    object_ = Column("object", JSON, nullable=False, default=dict)
    location = Column(JSON, nullable=False, default=dict)
    event_time_start = Column(DateTime, nullable=True)
    event_time_end = Column(DateTime, nullable=True)
    event_time_precision = Column(String(16), nullable=True)
    quantities = Column(JSON, nullable=False, default=list)
    identifiers = Column(JSON, nullable=False, default=list)
    outcomes = Column(JSON, nullable=False, default=list)
    modality = Column(String(24), nullable=False, default="reported")
    source_claim_type = Column(String(32), nullable=False, default="report")
    language = Column(String(16), nullable=False, default="unknown")
    source_text = Column(JSON, nullable=False, default=dict)
    confidence = Column(Float, nullable=False, default=0.0)
    extraction_method = Column(String(32), nullable=False, default="rules")
    model_version = Column(String(64), nullable=True)
    evidence_spans = Column(JSON, nullable=False, default=list)
    fingerprint = Column(String(64), nullable=False)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)
    updated_at = Column(DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)


class EventAssignmentLog(Base):
    __tablename__ = "event_assignment_logs"
    __table_args__ = (
        Index("ix_event_assignment_logs_content_created", "content_id", "created_at"),
        Index("ix_event_assignment_logs_event_created", "selected_event_id", "created_at"),
    )

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    content_id = Column(UUIDString, ForeignKey("contents.id", ondelete="CASCADE"), nullable=False)
    assignment_version = Column(String(64), nullable=False)
    selected_event_id = Column(String(32), ForeignKey("content_events.event_id"), nullable=True)
    decision = Column(String(32), nullable=False)
    relation = Column(String(32), nullable=False)
    assignment_method = Column(String(64), nullable=False)
    candidate_count = Column(Integer, nullable=False, default=0)
    candidates = Column(JSON, nullable=False, default=list)
    component_scores = Column(JSON, nullable=False, default=dict)
    hard_conflicts = Column(JSON, nullable=False, default=list)
    explain_reasons = Column(JSON, nullable=False, default=list)
    effective_threshold = Column(Float, nullable=True)
    latency_ms = Column(Float, nullable=False, default=0.0)
    shadow_only = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)


class EventRebalanceRun(Base):
    __tablename__ = "event_rebalance_runs"
    __table_args__ = (Index("ix_event_rebalance_runs_kind_created", "run_kind", "created_at"),)

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    run_kind = Column(String(16), nullable=False)
    status = Column(String(24), nullable=False, default="running")
    config_version = Column(String(64), nullable=False)
    cursor = Column(String(128), nullable=True)
    scanned_event_count = Column(Integer, nullable=False, default=0)
    candidate_pair_count = Column(Integer, nullable=False, default=0)
    filtered_closed_count = Column(Integer, nullable=False, default=0)
    checkpoint_count = Column(Integer, nullable=False, default=0)
    wake_reasons = Column(JSON, nullable=False, default=dict)
    budgets = Column(JSON, nullable=False, default=dict)
    summary = Column(JSON, nullable=False, default=dict)
    started_at = Column(DateTime, nullable=False, default=utcnow_naive)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)


class EventRebalanceSuggestion(Base):
    __tablename__ = "event_rebalance_suggestions"
    __table_args__ = (
        UniqueConstraint("suggestion_type", "fingerprint", name="uq_event_rebalance_suggestion"),
        Index("ix_event_rebalance_suggestions_status", "status", "created_at"),
    )

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id = Column(UUIDString, ForeignKey("event_rebalance_runs.id", ondelete="CASCADE"), nullable=False)
    suggestion_type = Column(String(16), nullable=False)
    event_ids = Column(JSON, nullable=False, default=list)
    reason = Column(Text, nullable=False)
    scores = Column(JSON, nullable=False, default=dict)
    evidence = Column(JSON, nullable=False, default=dict)
    fingerprint = Column(String(64), nullable=False)
    status = Column(String(24), nullable=False, default="pending")
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)
    reviewed_at = Column(DateTime, nullable=True)


class EventTodayDiffAudit(Base):
    __tablename__ = "event_today_diff_audits"
    __table_args__ = (
        UniqueConstraint("audit_date", "v0_digest_fingerprint", "v1_fingerprint", name="uq_event_today_diff"),
        Index("ix_event_today_diff_audits_date", "audit_date", "created_at"),
    )

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    audit_date = Column(String(10), nullable=False)
    v0_digest_fingerprint = Column(String(64), nullable=False)
    v1_fingerprint = Column(String(64), nullable=False)
    v0_items = Column(JSON, nullable=False, default=list)
    v1_items = Column(JSON, nullable=False, default=list)
    diff = Column(JSON, nullable=False, default=dict)
    assignment_version = Column(String(64), nullable=False)
    shadow_only = Column(Boolean, nullable=False, default=True)
    production_affected = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)


__all__ = [
    "EventAssignmentLog",
    "EventRebalanceRun",
    "EventRebalanceSuggestion",
    "EventSignature",
    "EventTodayDiffAudit",
]
