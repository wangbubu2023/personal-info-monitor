"""Durable scheduler, outbox, lineage, and Event migration records."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy import text as sa_text

from app.platform.persistence.database import Base, UUIDString
from app.utils.datetime import utcnow_naive


class SchedulerRun(Base):
    __tablename__ = "scheduler_runs"
    __table_args__ = (
        UniqueConstraint("schedule_id", "business_run_key", name="uq_scheduler_business_run"),
        Index("ix_scheduler_runs_state_scheduled", "state", "scheduled_for"),
    )

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    schedule_id = Column(String(128), nullable=False)
    business_run_key = Column(String(256), nullable=False)
    scheduled_for = Column(DateTime, nullable=False)
    policy_version = Column(String(32), nullable=False, default="v1")
    state = Column(String(32), nullable=False, default="pending")
    created_job_ids = Column(JSON, nullable=False, default=list)
    misfire_reason = Column(String(128), nullable=True)
    catch_up_of = Column(UUIDString, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)
    updated_at = Column(DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_outbox_idempotency_key"),
        Index("ix_outbox_dispatch", "state", "available_at"),
    )

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    event_type = Column(String(64), nullable=False)
    aggregate_type = Column(String(64), nullable=False)
    aggregate_id = Column(String(128), nullable=False)
    payload_schema_version = Column(Integer, nullable=False, default=1)
    payload = Column(JSON, nullable=False)
    idempotency_key = Column(String(512), nullable=False)
    state = Column(String(32), nullable=False, default="pending")
    available_at = Column(DateTime, nullable=False, default=utcnow_naive)
    attempt = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=5)
    locked_by = Column(String(128), nullable=True)
    lease_token = Column(String(64), nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)
    delivered_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"
    __table_args__ = (
        UniqueConstraint("delivery_key", name="uq_notification_delivery_key"),
        Index("ix_notification_delivery_outbox", "outbox_id"),
        Index("ix_notification_delivery_state_retry", "state", "next_retry_at"),
    )

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    outbox_id = Column(UUIDString, ForeignKey("outbox_events.id", ondelete="CASCADE"), nullable=False)
    channel = Column(String(32), nullable=False)
    recipient_ref = Column(String(512), nullable=False)
    delivery_key = Column(String(512), nullable=False)
    provider = Column(String(64), nullable=False)
    state = Column(String(32), nullable=False, default="pending")
    response_code = Column(Integer, nullable=True)
    response_excerpt = Column(Text, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    attempt = Column(Integer, nullable=False, default=0)
    next_retry_at = Column(DateTime, nullable=True)
    signature_key_version = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)
    delivered_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)


class LineageEdge(Base):
    __tablename__ = "lineage_edges"
    __table_args__ = (
        UniqueConstraint(
            "from_type", "from_id", "to_type", "to_id", "relation",
            name="uq_lineage_edge",
        ),
        Index("ix_lineage_from", "from_type", "from_id"),
        Index("ix_lineage_to", "to_type", "to_id"),
        Index("ix_lineage_trace", "trace_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    from_type = Column(String(64), nullable=False)
    from_id = Column(String(128), nullable=False)
    to_type = Column(String(64), nullable=False)
    to_id = Column(String(128), nullable=False)
    relation = Column(String(64), nullable=False)
    pipeline_version = Column(String(128), nullable=True)
    trace_id = Column(String(64), nullable=True)
    metadata_ = Column("metadata", JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)


class EventAlias(Base):
    __tablename__ = "event_aliases"
    __table_args__ = (
        UniqueConstraint("alias_type", "alias_value", name="uq_event_alias"),
        Index("ix_event_alias_canonical", "canonical_event_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    canonical_event_id = Column(String(32), ForeignKey("content_events.event_id"), nullable=False)
    alias_type = Column(String(32), nullable=False)
    alias_value = Column(String(128), nullable=False)
    valid_from = Column(DateTime, nullable=False, default=utcnow_naive)
    valid_to = Column(DateTime, nullable=True)
    redirect_enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)


class EventOperation(Base):
    __tablename__ = "event_operations"
    __table_args__ = (Index("ix_event_operations_event_created", "event_id", "created_at"),)

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    event_id = Column(String(32), ForeignKey("content_events.event_id"), nullable=False)
    operation_type = Column(String(32), nullable=False)
    input_event_ids = Column(JSON, nullable=False, default=list)
    output_event_ids = Column(JSON, nullable=False, default=list)
    reason = Column(Text, nullable=True)
    actor = Column(String(128), nullable=False, default="system")
    checkpoint = Column(String(128), nullable=True)
    checksum = Column(String(128), nullable=True)
    rollback_payload = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)


class EventMembershipV1(Base):
    __tablename__ = "event_memberships_v1"
    __table_args__ = (
        UniqueConstraint("event_id", "content_id", "assignment_version", name="uq_event_membership_v1"),
        Index("ix_event_memberships_v1_content", "content_id"),
        Index(
            "uq_event_memberships_v1_active_content_version",
            "content_id",
            "assignment_version",
            unique=True,
            sqlite_where=sa_text("active = 1"),
            postgresql_where=sa_text("active = true"),
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String(32), ForeignKey("content_events.event_id"), nullable=False)
    content_id = Column(UUIDString, ForeignKey("contents.id"), nullable=False)
    assignment_version = Column(String(64), nullable=False)
    role = Column(String(32), nullable=False, default="supporting")
    confidence = Column(Float, nullable=True)
    explanation = Column(JSON, nullable=False, default=dict)
    shadow_only = Column(Boolean, nullable=False, default=True)
    active = Column(Boolean, nullable=False, default=True)
    assignment_method = Column(String(64), nullable=False, default="rules")
    relation = Column(String(32), nullable=False, default="same_event")
    effective_threshold = Column(Float, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)


__all__ = [
    "EventAlias",
    "EventMembershipV1",
    "EventOperation",
    "LineageEdge",
    "NotificationDelivery",
    "OutboxEvent",
    "SchedulerRun",
]
