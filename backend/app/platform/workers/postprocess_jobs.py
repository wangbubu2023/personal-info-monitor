"""Durable post-process job bookkeeping for bounded workers."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import or_

from app.models.postprocess_job import PostprocessJob
from app.platform.persistence.database import SessionLocal
from app.utils.datetime import utcnow_naive

_TERMINAL_STATUSES = {"succeeded"}
_ACTIVE_STATUSES = {"pending", "running"}


def postprocess_idempotency_key(content_id: str, job_id: str | None = None) -> str:
    return f"{content_id}:{job_id or 'finish'}"


def ensure_postprocess_job(content_id: str, job_id: str | None = None) -> None:
    """Create or revive a durable job before it enters the execution cache."""
    key = postprocess_idempotency_key(content_id, job_id)
    now = utcnow_naive()
    db = SessionLocal()
    try:
        job = db.query(PostprocessJob).filter(PostprocessJob.idempotency_key == key).first()
        if job is None:
            db.add(
                PostprocessJob(
                    idempotency_key=key,
                    content_id=str(content_id),
                    job_id=job_id,
                    status="pending",
                    attempts=0,
                    max_attempts=3,
                    run_after=now,
                    created_at=now,
                    updated_at=now,
                )
            )
        elif job.status not in _ACTIVE_STATUSES:
            job.status = "pending"
            job.attempts = 0
            job.run_after = now
            job.locked_at = None
            job.started_at = None
            job.finished_at = None
            job.last_error = None
            job.updated_at = now
        db.commit()
    finally:
        db.close()


def claim_postprocess_job(content_id: str, job_id: str | None = None) -> bool:
    """Mark a due durable job running. Return False for stale duplicate cache entries."""
    key = postprocess_idempotency_key(content_id, job_id)
    now = utcnow_naive()
    db = SessionLocal()
    try:
        job = db.query(PostprocessJob).filter(PostprocessJob.idempotency_key == key).first()
        if job is None:
            job = PostprocessJob(
                idempotency_key=key,
                content_id=str(content_id),
                job_id=job_id,
                status="pending",
                attempts=0,
                max_attempts=3,
                run_after=now,
                created_at=now,
                updated_at=now,
            )
            db.add(job)
            db.flush()
        if job.status in _TERMINAL_STATUSES:
            return False
        if job.status == "running":
            return False
        if job.run_after and job.run_after > now:
            return False
        job.status = "running"
        job.attempts = int(job.attempts or 0) + 1
        job.locked_at = now
        job.started_at = now
        job.finished_at = None
        job.updated_at = now
        db.commit()
        return True
    finally:
        db.close()


def mark_postprocess_job_succeeded(content_id: str, job_id: str | None = None) -> None:
    key = postprocess_idempotency_key(content_id, job_id)
    now = utcnow_naive()
    db = SessionLocal()
    try:
        job = db.query(PostprocessJob).filter(PostprocessJob.idempotency_key == key).first()
        if job is None:
            return
        job.status = "succeeded"
        job.finished_at = now
        job.locked_at = None
        job.last_error = None
        job.updated_at = now
        db.commit()
    finally:
        db.close()


def mark_postprocess_job_failed(content_id: str, job_id: str | None, error: BaseException) -> str:
    """Persist failure and return the resulting status: ``pending`` or ``dead``."""
    key = postprocess_idempotency_key(content_id, job_id)
    now = utcnow_naive()
    db = SessionLocal()
    try:
        job = db.query(PostprocessJob).filter(PostprocessJob.idempotency_key == key).first()
        if job is None:
            return "dead"
        attempts = int(job.attempts or 0)
        max_attempts = int(job.max_attempts or 3)
        job.last_error = str(error)[:4000]
        job.locked_at = None
        job.finished_at = now
        if attempts >= max_attempts:
            job.status = "dead"
        else:
            delay_seconds = min(3600, 60 * (2 ** max(0, attempts - 1)))
            job.status = "pending"
            job.run_after = now + timedelta(seconds=delay_seconds)
        job.updated_at = now
        db.commit()
        return str(job.status)
    finally:
        db.close()


def due_postprocess_jobs(*, limit: int = 50) -> list[tuple[str, str | None]]:
    """Return due durable jobs for refilling the in-memory execution cache."""
    now = utcnow_naive()
    db = SessionLocal()
    try:
        rows = (
            db.query(PostprocessJob)
            .filter(
                PostprocessJob.status == "pending",
                or_(PostprocessJob.run_after.is_(None), PostprocessJob.run_after <= now),
            )
            .order_by(PostprocessJob.run_after.asc(), PostprocessJob.created_at.asc())
            .limit(max(1, int(limit or 1)))
            .all()
        )
        return [(str(row.content_id), row.job_id) for row in rows]
    finally:
        db.close()


def postprocess_completion_rate() -> dict[str, float | int]:
    """Small operational metric for checking postprocess reliability."""
    db = SessionLocal()
    try:
        total = db.query(PostprocessJob).count()
        succeeded = db.query(PostprocessJob).filter(PostprocessJob.status == "succeeded").count()
        failed = db.query(PostprocessJob).filter(PostprocessJob.status.in_(["failed", "dead"])).count()
        return {
            "total": total,
            "succeeded": succeeded,
            "failed": failed,
            "completion_rate": (succeeded / total) if total else 1.0,
        }
    finally:
        db.close()
