"""Durable fetch request model."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint

from app.database import Base, UUIDString
from app.utils.datetime import utcnow_naive


class FetchJob(Base):
    __tablename__ = "fetch_jobs"
    __table_args__ = (
        UniqueConstraint("business_key", name="uq_fetch_jobs_business_key"),
        Index("ix_fetch_jobs_dispatch", "state", "priority", "not_before"),
        Index("ix_fetch_jobs_lease", "state", "locked_by", "lease_token"),
        Index("ix_fetch_jobs_source_id", "source_id"),
    )

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    job_type = Column(String(32), nullable=False, default="fetch")
    business_key = Column(String(512), nullable=False)
    trace_id = Column(String(64), nullable=False, default=lambda: uuid.uuid4().hex)
    source_id = Column(UUIDString, ForeignKey("sources.id"), nullable=False)
    fetch_kind = Column(String(32), nullable=False)
    due_window = Column(DateTime, nullable=False)
    state = Column(String(32), nullable=False, default="pending")
    priority = Column(Integer, nullable=False, default=100)
    payload_schema_version = Column(Integer, nullable=False, default=1)
    payload = Column(JSON, nullable=False, default=dict)
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    not_before = Column(DateTime, nullable=False, default=utcnow_naive)
    deadline = Column(DateTime, nullable=True)
    locked_by = Column(String(128), nullable=True)
    lease_token = Column(String(64), nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
    heartbeat_at = Column(DateTime, nullable=True)
    enqueued_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    failure_code = Column(String(64), nullable=True)
    failure_message = Column(Text, nullable=True)
    failure_retryable = Column(Boolean, nullable=True)
    abandoned_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive)
    updated_at = Column(DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)


__all__ = ["FetchJob"]
