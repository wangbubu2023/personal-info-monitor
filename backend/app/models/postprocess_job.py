"""Durable post-processing job model."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, Text, UniqueConstraint

from app.database import Base, UUIDString
from app.utils.datetime import utcnow_naive


class PostprocessJob(Base):
    """SQLite-backed truth source for ingest finalization jobs."""

    __tablename__ = "postprocess_jobs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_postprocess_jobs_idempotency_key"),
        Index("ix_postprocess_jobs_status_run_after", "status", "run_after"),
        Index("ix_postprocess_jobs_content_id", "content_id"),
    )

    id = Column(UUIDString, primary_key=True, default=lambda: str(uuid.uuid4()))
    idempotency_key = Column(String(512), nullable=False)
    content_id = Column(UUIDString, nullable=False)
    job_id = Column(String(128), nullable=True)
    status = Column(String(32), nullable=False, default="pending")
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    run_after = Column(DateTime, nullable=False, default=utcnow_naive)
    locked_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    failure_code = Column(String(64), nullable=True)
    failure_severity = Column(String(16), nullable=True)
    failure_retryable = Column(Boolean, nullable=True)
    created_at = Column(DateTime, default=utcnow_naive, nullable=False)
    updated_at = Column(DateTime, default=utcnow_naive, onupdate=utcnow_naive, nullable=False)
