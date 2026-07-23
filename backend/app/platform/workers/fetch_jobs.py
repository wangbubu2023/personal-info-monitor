"""Durable FetchJob creation, claiming and recovery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError

from app.models.fetch_job import FetchJob
from app.platform.observability.failure_classifier import classify_exception
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
        return FetchDispatchResult(sid, kind, str(job.id), key, True)
    finally:
        db.close()


def mark_fetch_job_enqueued(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.query(FetchJob).filter(FetchJob.id == job_id).first()
        if job is not None and job.state == "pending":
            job.enqueued_at = utcnow_naive()
            job.updated_at = utcnow_naive()
            db.commit()
    finally:
        db.close()


def claim_fetch_job(job_id: str) -> bool:
    db = SessionLocal()
    try:
        job = db.query(FetchJob).filter(FetchJob.id == job_id).first()
        if job is None or job.state != "pending" or (job.not_before and job.not_before > utcnow_naive()):
            return False
        job.state = "running"
        job.attempts = int(job.attempts or 0) + 1
        job.started_at = utcnow_naive()
        job.updated_at = utcnow_naive()
        db.commit()
        return True
    finally:
        db.close()


def mark_fetch_job_succeeded(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.query(FetchJob).filter(FetchJob.id == job_id).first()
        if job is not None:
            job.state = "succeeded"
            job.completed_at = utcnow_naive()
            job.failure_code = None
            job.failure_message = None
            job.failure_retryable = None
            job.updated_at = utcnow_naive()
            db.commit()
    finally:
        db.close()


def mark_fetch_job_failed(job_id: str, error: BaseException) -> str:
    db = SessionLocal()
    try:
        job = db.query(FetchJob).filter(FetchJob.id == job_id).first()
        if job is None:
            return "dead"
        failure = classify_exception(error)
        attempts = int(job.attempts or 0)
        retryable = bool(failure.retryable and attempts < int(job.max_attempts or 3))
        job.failure_code = str(failure.code)
        job.failure_message = failure.message[:4000]
        job.failure_retryable = bool(failure.retryable)
        job.completed_at = utcnow_naive()
        if retryable:
            job.state = "pending"
            job.not_before = utcnow_naive() + timedelta(seconds=min(3600, 60 * (2 ** max(0, attempts - 1))))
            job.enqueued_at = None
        else:
            job.state = "dead"
        job.updated_at = utcnow_naive()
        db.commit()
        return str(job.state)
    finally:
        db.close()


def due_fetch_jobs(*, limit: int = 200) -> list[tuple[str, str, bool]]:
    db = SessionLocal()
    try:
        rows = (
            db.query(FetchJob)
            .filter(
                FetchJob.state == "pending",
                FetchJob.not_before <= utcnow_naive(),
                FetchJob.enqueued_at.is_(None),
            )
            .order_by(FetchJob.not_before.asc(), FetchJob.created_at.asc())
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
            .filter(FetchJob.state == "pending", FetchJob.enqueued_at.is_not(None))
            .update({"enqueued_at": None, "updated_at": utcnow_naive()}, synchronize_session=False)
        )
        if count:
            db.commit()
        return int(count or 0)
    finally:
        db.close()


__all__ = [
    "FetchDispatchResult",
    "claim_fetch_job",
    "create_fetch_job",
    "due_fetch_jobs",
    "fetch_business_key",
    "mark_fetch_job_enqueued",
    "mark_fetch_job_failed",
    "mark_fetch_job_succeeded",
    "normalize_due_window",
    "reset_pending_fetch_enqueued",
]
