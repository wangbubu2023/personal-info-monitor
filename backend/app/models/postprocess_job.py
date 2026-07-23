"""Durable post-processing job model."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, JSON, String, Text, UniqueConstraint

from app.database import Base, UUIDString
from app.utils.datetime import utcnow_naive


class PostprocessJob(Base):
    """SQLite-backed truth source for ingest finalization jobs."""

    __tablename__ = "postprocess_jobs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_postprocess_jobs_idempotency_key"),
        Index("ix_postprocess_jobs_dispatch", "status", "priority", "run_after"),
        Index("ix_postprocess_jobs_lease", "status", "locked_by", "lease_token"),
        Index("ix_postprocess_jobs_content_id", "content_id"),
    )

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    job_type = Column(String(32), nullable=False, default="postprocess")
    idempotency_key = Column(String(512), nullable=False)
    trace_id = Column(String(64), nullable=False, default=lambda: uuid.uuid4().hex)
    content_id = Column(UUIDString, nullable=False)
    job_id = Column(String(128), nullable=True)
    pipeline_stage = Column(String(64), nullable=False, default="finish")
    pipeline_version = Column(String(128), nullable=False, default="v1")
    status = Column(String(32), nullable=False, default="pending")
    priority = Column(Integer, nullable=False, default=100)
    payload_schema_version = Column(Integer, nullable=False, default=1)
    payload = Column(JSON, nullable=False, default=dict)
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    run_after = Column(DateTime, nullable=False, default=utcnow_naive)
    deadline = Column(DateTime, nullable=True)
    locked_by = Column(String(128), nullable=True)
    lease_token = Column(String(64), nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
    heartbeat_at = Column(DateTime, nullable=True)
    locked_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    failure_code = Column(String(64), nullable=True)
    failure_severity = Column(String(16), nullable=True)
    failure_retryable = Column(Boolean, nullable=True)
    abandoned_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow_naive, nullable=False)
    updated_at = Column(DateTime, default=utcnow_naive, onupdate=utcnow_naive, nullable=False)
