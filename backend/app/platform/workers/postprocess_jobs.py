"""Durable post-process job bookkeeping for bounded workers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
import os
from threading import Lock
import uuid

from sqlalchemy import and_, or_

from app.models.postprocess_job import PostprocessJob
from app.platform.observability.failure_classifier import classify_exception
from app.platform.observability.logger import get_logger
from app.platform.observability.metrics import reliability_metrics
from app.platform.persistence.database import SessionLocal
from app.utils.datetime import utcnow_naive

logger = get_logger(__name__)

_TERMINAL_STATUSES = {"succeeded"}
_ACTIVE_STATUSES = {"pending", "leased", "running", "retry_wait"}
POSTPROCESS_STALE_AFTER_SECONDS = 10 * 60


@dataclass(frozen=True)
class PostprocessLease:
    content_id: str
    job_id: str | None
    owner: str
    token: str
    expires_at: datetime


_claimed_leases: dict[str, PostprocessLease] = {}
_claimed_leases_lock = Lock()


def _pipeline_identity(job_id: str | None) -> tuple[str, str]:
    raw = str(job_id or "v1")
    if raw == "listing-translation":
        return "listing_translation", "v1"
    if raw.startswith("finish:"):
        parts = raw.split(":", 2)
        return "finish", parts[1] if len(parts) > 1 and parts[1] else "v1"
    return "finish", raw


def postprocess_idempotency_key(content_id: str, job_id: str | None = None) -> str:
    stage, version = _pipeline_identity(job_id)
    raw = str(job_id or version)
    # ``finish:<pipeline-version>:<content-fingerprint>`` is the durable
    # business identity emitted by StorageStage.  Keep the fingerprint in the
    # key so a substantive update is not suppressed by an earlier success,
    # while retaining the actual pipeline version in its dedicated column.
    identity = raw.removeprefix("finish:") if raw.startswith("finish:") else version
    return f"{content_id}:{stage}:{identity or version}"


def ensure_postprocess_job(content_id: str, job_id: str | None = None) -> None:
    """Create or revive a durable job before it enters the execution cache."""
    ensure_postprocess_jobs([(content_id, job_id)])


def ensure_postprocess_jobs(jobs: list[tuple[str, str | None]]) -> int:
    """Create or revive many durable jobs in one SQLite transaction.

    v1.6 originally opened and committed one session for every content item.
    A source returning 20 items therefore serialized 20 transactions before
    its fetch worker could finish, and 20 concurrent sources amplified that
    into a SQLite write storm.  Load all existing idempotency keys once and
    persist the whole source batch with a single commit.

    Returns the number of rows created or revived. Active jobs are left
    untouched and do not cause a write transaction.
    """
    normalized: dict[str, tuple[str, str | None]] = {}
    for content_id, job_id in jobs:
        cid = str(content_id or "").strip()
        if not cid:
            continue
        normalized[postprocess_idempotency_key(cid, job_id)] = (cid, job_id)
    if not normalized:
        return 0

    now = utcnow_naive()
    db = SessionLocal()
    try:
        existing = (
            db.query(PostprocessJob)
            .filter(PostprocessJob.idempotency_key.in_(list(normalized)))
            .all()
        )
        existing_by_key = {job.idempotency_key: job for job in existing}
        changed = 0
        for key, (content_id, job_id) in normalized.items():
            stage, version = _pipeline_identity(job_id)
            job = existing_by_key.get(key)
            if job is None:
                db.add(
                    PostprocessJob(
                        idempotency_key=key,
                        content_id=content_id,
                        job_id=job_id,
                        pipeline_stage=stage,
                        pipeline_version=version,
                        status="pending",
                        attempts=0,
                        max_attempts=3,
                        run_after=now,
                        created_at=now,
                        updated_at=now,
                    )
                )
                changed += 1
                continue
            if job.status in _ACTIVE_STATUSES or job.status in _TERMINAL_STATUSES:
                continue
            job.status = "pending"
            job.attempts = 0
            job.run_after = now
            job.locked_at = None
            job.locked_by = None
            job.lease_token = None
            job.lease_expires_at = None
            job.heartbeat_at = None
            job.started_at = None
            job.finished_at = None
            job.last_error = None
            job.updated_at = now
            changed += 1
        if changed:
            db.commit()
            reliability_metrics.record("postprocess_accepted", changed)
        return changed
    finally:
        db.close()


def acquire_postprocess_job(
    content_id: str,
    job_id: str | None = None,
    *,
    owner: str | None = None,
    lease_seconds: int = 120,
) -> PostprocessLease | None:
    """Acquire or reclaim a due postprocess job with an owner/token fence."""
    key = postprocess_idempotency_key(content_id, job_id)
    now = utcnow_naive()
    worker = owner or f"{os.getpid()}:{uuid.uuid4().hex[:12]}"
    token = uuid.uuid4().hex
    expires = now + timedelta(seconds=max(5, int(lease_seconds)))
    db = SessionLocal()
    try:
        job = db.query(PostprocessJob).filter(PostprocessJob.idempotency_key == key).first()
        if job is None:
            stage, version = _pipeline_identity(job_id)
            job = PostprocessJob(
                idempotency_key=key,
                content_id=str(content_id),
                job_id=job_id,
                pipeline_stage=stage,
                pipeline_version=version,
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
            return None
        if job.status in {"leased", "running"}:
            locked_at = job.locked_at or job.started_at
            if job.lease_expires_at is not None:
                if job.lease_expires_at > now:
                    return None
            else:
                stale_before = now - timedelta(seconds=POSTPROCESS_STALE_AFTER_SECONDS)
                if not locked_at or locked_at > stale_before:
                    return None
            if int(job.attempts or 0) >= int(job.max_attempts or 3):
                job.status = "dead"
                job.locked_at = None
                job.locked_by = None
                job.lease_token = None
                job.lease_expires_at = None
                job.finished_at = now
                job.last_error = (job.last_error or "")[:3900] + " [stale job exhausted retry limit]"
                job.updated_at = now
                db.commit()
                return None
            logger.warning(
                "Reclaiming stale postprocess job %s (locked_at=%s, attempts=%s)",
                key,
                locked_at,
                job.attempts,
            )
            job.status = "pending"
            job.locked_at = None
            job.started_at = None
            job.finished_at = None
            job.run_after = now
        if job.run_after and job.run_after > now:
            return None
        job.status = "running"
        job.attempts = int(job.attempts or 0) + 1
        job.locked_at = now
        job.locked_by = worker
        job.lease_token = token
        job.lease_expires_at = expires
        job.heartbeat_at = now
        job.started_at = now
        job.finished_at = None
        job.updated_at = now
        queue_age_ms = max(0.0, (now - job.created_at).total_seconds() * 1000) if job.created_at else 0.0
        db.commit()
        reliability_metrics.record("postprocess_leased")
        reliability_metrics.record("postprocess_queue_age_ms", queue_age_ms)
        return PostprocessLease(str(content_id), job_id, worker, token, expires)
    finally:
        db.close()


def claim_postprocess_job(content_id: str, job_id: str | None = None) -> bool:
    """Backward-compatible claim surface; new workers use the lease object."""
    lease = acquire_postprocess_job(content_id, job_id, owner=f"worker:{os.getpid()}")
    if lease is None:
        return False
    key = postprocess_idempotency_key(content_id, job_id)
    with _claimed_leases_lock:
        _claimed_leases[key] = lease
    return True


def take_claimed_postprocess_lease(content_id: str, job_id: str | None) -> PostprocessLease | None:
    key = postprocess_idempotency_key(content_id, job_id)
    with _claimed_leases_lock:
        return _claimed_leases.pop(key, None)


def heartbeat_postprocess_job(
    content_id: str,
    job_id: str | None,
    owner: str,
    token: str,
    *,
    lease_seconds: int = 120,
) -> bool:
    key = postprocess_idempotency_key(content_id, job_id)
    now = utcnow_naive()
    db = SessionLocal()
    try:
        changed = (
            db.query(PostprocessJob)
            .filter(
                PostprocessJob.idempotency_key == key,
                PostprocessJob.status == "running",
                PostprocessJob.locked_by == owner,
                PostprocessJob.lease_token == token,
            )
            .update(
                {
                    PostprocessJob.heartbeat_at: now,
                    PostprocessJob.lease_expires_at: now + timedelta(seconds=max(5, int(lease_seconds))),
                    PostprocessJob.updated_at: now,
                },
                synchronize_session=False,
            )
        )
        if changed:
            db.commit()
        else:
            db.rollback()
        if changed != 1:
            reliability_metrics.record("postprocess_heartbeat_miss")
        return changed == 1
    finally:
        db.close()


def _lease_filter(key: str, owner: str | None, token: str | None):
    clauses = [PostprocessJob.idempotency_key == key]
    if owner is not None or token is not None:
        clauses.extend([PostprocessJob.locked_by == owner, PostprocessJob.lease_token == token])
    return clauses


def recover_stale_postprocess_jobs(*, stale_after_seconds: int = POSTPROCESS_STALE_AFTER_SECONDS) -> int:
    """Return abandoned running jobs to the durable pending queue.

    A process restart cancels the in-memory worker but previously left its
    durable row as ``running`` forever. Those rows were then invisible to
    ``due_postprocess_jobs`` and could never be retried.
    """
    now = utcnow_naive()
    stale_before = now - timedelta(seconds=max(1, int(stale_after_seconds)))
    db = SessionLocal()
    recovered = 0
    try:
        jobs = (
            db.query(PostprocessJob)
            .filter(
                PostprocessJob.status == "running",
                or_(
                    PostprocessJob.lease_expires_at <= now,
                    PostprocessJob.locked_at <= stale_before,
                    PostprocessJob.locked_at.is_(None),
                    PostprocessJob.started_at <= stale_before,
                ),
            )
            .all()
        )
        for job in jobs:
            attempts = int(job.attempts or 0)
            max_attempts = int(job.max_attempts or 3)
            if attempts >= max_attempts:
                job.status = "dead"
                job.finished_at = now
            else:
                job.status = "pending"
                job.run_after = now
                job.finished_at = None
            job.locked_at = None
            job.locked_by = None
            job.lease_token = None
            job.lease_expires_at = None
            job.started_at = None
            job.last_error = (job.last_error or "")[:3900] + " [recovered stale running job]"
            job.updated_at = now
            recovered += 1
        if recovered:
            db.commit()
        return recovered
    finally:
        db.close()


def mark_postprocess_job_succeeded(
    content_id: str,
    job_id: str | None = None,
    *,
    owner: str | None = None,
    token: str | None = None,
) -> bool:
    key = postprocess_idempotency_key(content_id, job_id)
    now = utcnow_naive()
    db = SessionLocal()
    try:
        job = db.query(PostprocessJob).filter(*_lease_filter(key, owner, token)).first()
        if job is None:
            return False
        job.status = "succeeded"
        job.finished_at = now
        job.locked_at = None
        job.locked_by = None
        job.lease_token = None
        job.lease_expires_at = None
        job.last_error = None
        job.failure_code = None
        job.failure_severity = None
        job.failure_retryable = None
        job.updated_at = now
        db.commit()
        reliability_metrics.record("postprocess_succeeded")
        return True
    finally:
        db.close()


def mark_postprocess_job_abandoned(
    content_id: str,
    job_id: str | None,
    *,
    owner: str,
    token: str,
    reason: str,
) -> bool:
    key = postprocess_idempotency_key(content_id, job_id)
    now = utcnow_naive()
    db = SessionLocal()
    try:
        job = db.query(PostprocessJob).filter(*_lease_filter(key, owner, token)).first()
        if job is None:
            return False
        job.status = "abandoned"
        job.abandoned_reason = str(reason)[:4000]
        job.finished_at = now
        job.locked_at = None
        job.locked_by = None
        job.lease_token = None
        job.lease_expires_at = None
        job.updated_at = now
        db.commit()
        return True
    finally:
        db.close()


def mark_postprocess_job_failed(
    content_id: str,
    job_id: str | None,
    error: BaseException,
    *,
    owner: str | None = None,
    token: str | None = None,
) -> str:
    """Persist failure and return the resulting status: ``pending`` or ``dead``."""
    key = postprocess_idempotency_key(content_id, job_id)
    now = utcnow_naive()
    db = SessionLocal()
    try:
        job = db.query(PostprocessJob).filter(*_lease_filter(key, owner, token)).first()
        if job is None:
            return "cas_conflict"
        attempts = int(job.attempts or 0)
        max_attempts = int(job.max_attempts or 3)
        failure = classify_exception(error)
        failure_code = getattr(failure.code, "value", failure.code)
        job.last_error = f"[{failure_code}] {failure.message}"[:4000]
        job.failure_code = str(failure_code)
        job.failure_severity = failure.severity
        job.failure_retryable = failure.retryable
        job.locked_at = None
        job.locked_by = None
        job.lease_token = None
        job.lease_expires_at = None
        job.finished_at = now
        if not failure.retryable or attempts >= max_attempts:
            job.status = "dead"
        else:
            delay_seconds = min(3600, 60 * (2 ** max(0, attempts - 1)))
            job.status = "retry_wait"
            job.run_after = now + timedelta(seconds=delay_seconds)
        job.updated_at = now
        db.commit()
        reliability_metrics.record("postprocess_retry" if job.status == "retry_wait" else "postprocess_dead")
        return "pending" if job.status == "retry_wait" else str(job.status)
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
                PostprocessJob.status.in_(["pending", "retry_wait", "abandoned"]),
                or_(PostprocessJob.run_after.is_(None), PostprocessJob.run_after <= now),
            )
            .order_by(PostprocessJob.priority.asc(), PostprocessJob.run_after.asc(), PostprocessJob.created_at.asc())
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
