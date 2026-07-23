"""Durable FetchJob creation, claiming and recovery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import os
from threading import Lock
import uuid

from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError

from app.models.fetch_job import FetchJob
from app.platform.observability.failure_classifier import classify_exception
from app.platform.observability.metrics import reliability_metrics
from app.platform.persistence.database import SessionLocal
from app.utils.datetime import utcnow_naive


@dataclass(frozen=True)
class FetchDispatchResult:
    source_id: str
    fetch_kind: str
    job_id: str | None
    business_key: str
    persisted: bool
    enqueued: bool = False
    duplicate: bool = False
    rejected: bool = False
    state: str = "pending"
    reason: str | None = None

    @property
    def accepted(self) -> bool:
        return self.persisted and not self.rejected

    def __bool__(self) -> bool:
        return self.enqueued


@dataclass(frozen=True)
class FetchLease:
    job_id: str
    owner: str
    token: str
    expires_at: datetime


_claimed_leases: dict[str, FetchLease] = {}
_claimed_leases_lock = Lock()


def normalize_due_window(value: datetime | None = None, *, window_seconds: int = 60) -> datetime:
    current = value or utcnow_naive()
    seconds = max(1, int(window_seconds))
    epoch = int(current.timestamp())
    return datetime.utcfromtimestamp(epoch - (epoch % seconds))


def fetch_business_key(source_id: str, fetch_kind: str, due_window: datetime) -> str:
    return f"{str(source_id)}:{fetch_kind}:{due_window.isoformat()}"


def create_fetch_job(
    source_id: str,
    *,
    fetch_kind: str,
    due_window: datetime | None = None,
    not_before: datetime | None = None,
    window_seconds: int = 60,
) -> FetchDispatchResult:
    sid = str(source_id or "").strip()
    kind = str(fetch_kind or "scheduled").strip().lower()
    window = normalize_due_window(due_window, window_seconds=window_seconds)
    key = fetch_business_key(sid, kind, window)
    db = SessionLocal()
    try:
        existing = db.query(FetchJob).filter(FetchJob.business_key == key).first()
        if existing is not None:
            return FetchDispatchResult(
                sid, kind, str(existing.id), key, True,
                duplicate=True, state=str(existing.state), reason="duplicate_business_key",
            )
        now = utcnow_naive()
        job = FetchJob(
            business_key=key,
            source_id=sid,
            fetch_kind=kind,
            due_window=window,
            state="pending",
            not_before=not_before or now,
            created_at=now,
            updated_at=now,
        )
        db.add(job)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            existing = db.query(FetchJob).filter(FetchJob.business_key == key).one()
            return FetchDispatchResult(
                sid, kind, str(existing.id), key, True,
                duplicate=True, state=str(existing.state), reason="duplicate_business_key",
            )
        reliability_metrics.record("fetch_accepted")
        return FetchDispatchResult(sid, kind, str(job.id), key, True)
    finally:
        db.close()


def mark_fetch_job_enqueued(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.query(FetchJob).filter(FetchJob.id == job_id).first()
        if job is not None and job.state in {"pending", "retry_wait", "abandoned"}:
            job.enqueued_at = utcnow_naive()
            job.updated_at = utcnow_naive()
            db.commit()
    finally:
        db.close()


def acquire_fetch_job(
    job_id: str,
    *,
    owner: str | None = None,
    lease_seconds: int = 120,
) -> FetchLease | None:
    """Acquire a due job with one CAS update.

    Expired owners are fenced out by the new token. Completion and heartbeat
    must present both values, so a late result cannot overwrite a reclaimed
    job.
    """
    now = utcnow_naive()
    worker = owner or f"{os.getpid()}:{uuid.uuid4().hex[:12]}"
    token = uuid.uuid4().hex
    expires = now + timedelta(seconds=max(5, int(lease_seconds)))
    db = SessionLocal()
    try:
        eligible = and_(
            FetchJob.id == job_id,
            FetchJob.not_before <= now,
            or_(
                FetchJob.state.in_(["pending", "retry_wait", "abandoned"]),
                and_(
                    FetchJob.state.in_(["leased", "running"]),
                    FetchJob.lease_expires_at.is_not(None),
                    FetchJob.lease_expires_at <= now,
                ),
            ),
        )
        changed = db.query(FetchJob).filter(eligible).update(
            {
                FetchJob.state: "running",
                FetchJob.locked_by: worker,
                FetchJob.lease_token: token,
                FetchJob.lease_expires_at: expires,
                FetchJob.heartbeat_at: now,
                FetchJob.started_at: now,
                FetchJob.completed_at: None,
                FetchJob.abandoned_reason: None,
                FetchJob.attempts: FetchJob.attempts + 1,
                FetchJob.updated_at: now,
            },
            synchronize_session=False,
        )
        if changed != 1:
            db.rollback()
            return None
        created_at = db.query(FetchJob.created_at).filter(FetchJob.id == job_id).scalar()
        db.commit()
        reliability_metrics.record("fetch_leased")
        if created_at is not None:
            reliability_metrics.record(
                "fetch_queue_age_ms",
                max(0.0, (now - created_at).total_seconds() * 1000),
            )
        return FetchLease(str(job_id), worker, token, expires)
    finally:
        db.close()


def claim_fetch_job(job_id: str) -> bool:
    """Backward-compatible claim surface; new workers use ``acquire_fetch_job``."""
    lease = acquire_fetch_job(job_id, owner=f"worker:{os.getpid()}")
    if lease is None:
        return False
    with _claimed_leases_lock:
        _claimed_leases[str(job_id)] = lease
    return True


def take_claimed_fetch_lease(job_id: str) -> FetchLease | None:
    with _claimed_leases_lock:
        return _claimed_leases.pop(str(job_id), None)


def heartbeat_fetch_job(
    job_id: str,
    owner: str,
    token: str,
    *,
    lease_seconds: int = 120,
) -> bool:
    now = utcnow_naive()
    db = SessionLocal()
    try:
        changed = (
            db.query(FetchJob)
            .filter(
                FetchJob.id == job_id,
                FetchJob.state == "running",
                FetchJob.locked_by == owner,
                FetchJob.lease_token == token,
            )
            .update(
                {
                    FetchJob.heartbeat_at: now,
                    FetchJob.lease_expires_at: now + timedelta(seconds=max(5, int(lease_seconds))),
                    FetchJob.updated_at: now,
                },
                synchronize_session=False,
            )
        )
        if changed:
            db.commit()
        else:
            db.rollback()
        if changed != 1:
            reliability_metrics.record("fetch_heartbeat_miss")
        return changed == 1
    finally:
        db.close()


def _lease_filter(job_id: str, owner: str | None, token: str | None):
    clauses = [FetchJob.id == job_id]
    if owner is not None or token is not None:
        clauses.extend([FetchJob.locked_by == owner, FetchJob.lease_token == token])
    return clauses


def mark_fetch_job_succeeded(
    job_id: str,
    *,
    owner: str | None = None,
    token: str | None = None,
) -> bool:
    now = utcnow_naive()
    db = SessionLocal()
    try:
        changed = db.query(FetchJob).filter(*_lease_filter(job_id, owner, token)).update(
            {
                FetchJob.state: "succeeded",
                FetchJob.completed_at: now,
                FetchJob.failure_code: None,
                FetchJob.failure_message: None,
                FetchJob.failure_retryable: None,
                FetchJob.locked_by: None,
                FetchJob.lease_token: None,
                FetchJob.lease_expires_at: None,
                FetchJob.updated_at: now,
            },
            synchronize_session=False,
        )
        if changed:
            db.commit()
        else:
            db.rollback()
        reliability_metrics.record("fetch_succeeded" if changed == 1 else "fetch_cas_conflict")
        return changed == 1
    finally:
        db.close()


def mark_fetch_job_abandoned(
    job_id: str,
    *,
    owner: str,
    token: str,
    reason: str,
) -> bool:
    now = utcnow_naive()
    db = SessionLocal()
    try:
        changed = db.query(FetchJob).filter(*_lease_filter(job_id, owner, token)).update(
            {
                FetchJob.state: "abandoned",
                FetchJob.abandoned_reason: str(reason)[:4000],
                FetchJob.completed_at: now,
                FetchJob.locked_by: None,
                FetchJob.lease_token: None,
                FetchJob.lease_expires_at: None,
                FetchJob.updated_at: now,
            },
            synchronize_session=False,
        )
        if changed:
            db.commit()
        else:
            db.rollback()
        return changed == 1
    finally:
        db.close()


def mark_fetch_job_failed(
    job_id: str,
    error: BaseException,
    *,
    owner: str | None = None,
    token: str | None = None,
) -> str:
    db = SessionLocal()
    try:
        job = db.query(FetchJob).filter(*_lease_filter(job_id, owner, token)).first()
        if job is None:
            return "cas_conflict"
        failure = classify_exception(error)
        attempts = int(job.attempts or 0)
        retryable = bool(failure.retryable and attempts < int(job.max_attempts or 3))
        job.failure_code = str(failure.code)
        job.failure_message = failure.message[:4000]
        job.failure_retryable = bool(failure.retryable)
        job.completed_at = utcnow_naive()
        if retryable:
            job.state = "retry_wait"
            job.not_before = utcnow_naive() + timedelta(seconds=min(3600, 60 * (2 ** max(0, attempts - 1))))
            job.enqueued_at = None
        else:
            job.state = "dead"
        job.locked_by = None
        job.lease_token = None
        job.lease_expires_at = None
        job.updated_at = utcnow_naive()
        db.commit()
        reliability_metrics.record("fetch_retry" if job.state == "retry_wait" else "fetch_dead")
        return str(job.state)
    finally:
        db.close()


def due_fetch_jobs(*, limit: int = 200) -> list[tuple[str, str, bool]]:
    db = SessionLocal()
    try:
        rows = (
            db.query(FetchJob)
            .filter(
                FetchJob.state.in_(["pending", "retry_wait", "abandoned"]),
                FetchJob.not_before <= utcnow_naive(),
                FetchJob.enqueued_at.is_(None),
            )
            .order_by(FetchJob.priority.asc(), FetchJob.not_before.asc(), FetchJob.created_at.asc())
            .limit(max(1, int(limit)))
            .all()
        )
        return [
            (str(row.id), str(row.source_id), row.fetch_kind in {"manual", "bulk_manual"})
            for row in rows
        ]
    finally:
        db.close()


def reset_pending_fetch_enqueued() -> int:
    """Clear volatile execution-cache markers after a process restart."""
    db = SessionLocal()
    try:
        count = (
            db.query(FetchJob)
            .filter(FetchJob.state.in_(["pending", "retry_wait", "abandoned"]), FetchJob.enqueued_at.is_not(None))
            .update({"enqueued_at": None, "updated_at": utcnow_naive()}, synchronize_session=False)
        )
        if count:
            db.commit()
        return int(count or 0)
    finally:
        db.close()


__all__ = [
    "FetchDispatchResult",
    "FetchLease",
    "acquire_fetch_job",
    "claim_fetch_job",
    "create_fetch_job",
    "due_fetch_jobs",
    "fetch_business_key",
    "heartbeat_fetch_job",
    "mark_fetch_job_abandoned",
    "mark_fetch_job_enqueued",
    "mark_fetch_job_failed",
    "mark_fetch_job_succeeded",
    "normalize_due_window",
    "reset_pending_fetch_enqueued",
    "take_claimed_fetch_lease",
]
