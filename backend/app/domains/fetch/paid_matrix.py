"""Paid-source matrix, recovery drill, and canary audit services."""

from __future__ import annotations

from datetime import datetime, timedelta
import uuid

from sqlalchemy import case, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.paid_matrix import DailyCanaryRun, PaidSourceMatrixAudit, SessionRecoveryAudit
from app.utils.datetime import utcnow_naive

MIN_READABLE_BODY_LENGTH = 100
PAYWALL_KEYWORDS = [
    "subscribe to read",
    "become a member",
    "exclusive for subscribers",
    "paywall",
    "create an account to continue reading",
    "订阅解锁全文",
    "付费阅读",
]


def check_readability(body_text: str | None) -> tuple[bool, str | None]:
    """Recognize a readable article body, not merely a successful HTTP response."""

    if not body_text or len(body_text.strip()) < MIN_READABLE_BODY_LENGTH:
        return False, "BODY_TOO_SHORT"
    lower_text = body_text.lower()
    for keyword in PAYWALL_KEYWORDS:
        if keyword in lower_text:
            return False, "PAYWALL_RESIDUAL_DETECTED"
    return True, None


def _recovery_action(failure_code: str | None) -> str | None:
    if not failure_code:
        return None
    if failure_code == "PAYWALL_RESIDUAL_DETECTED":
        return "RE_AUTHENTICATE_COOKIE"
    if failure_code == "BODY_TOO_SHORT":
        return "CHECK_SELECTOR_OR_PARSER"
    return "INSPECT_NETWORK_AND_PROXY"


def record_paid_source_result(
    db: Session,
    source_id: str,
    body_text: str | None,
    discovery_url: str | None = None,
    validation_url: str | None = None,
    http_status: int = 200,
) -> PaidSourceMatrixAudit:
    """Persist one paid-source probe and its actual seven-day success rate."""

    body_readable, body_failure = check_readability(body_text)
    http_ok = 200 <= int(http_status) < 300
    is_success = http_ok and body_readable
    failure_code = None if is_success else (f"HTTP_{http_status}" if not http_ok else body_failure)
    now = utcnow_naive()
    cutoff = now - timedelta(days=7)

    previous_success = (
        db.query(func.max(PaidSourceMatrixAudit.last_readable_success_at))
        .filter(PaidSourceMatrixAudit.source_id == source_id)
        .scalar()
    )
    audit = PaidSourceMatrixAudit(
        id=str(uuid.uuid4()),
        source_id=source_id,
        discovery_url=discovery_url,
        validation_url=validation_url,
        last_readable_success_at=now if is_success else previous_success,
        success_rate_7d=0.0,
        failure_code=failure_code,
        recovery_action=_recovery_action(failure_code),
        created_at=now,
    )
    db.add(audit)
    db.flush()

    total, successful = (
        db.query(
            func.count(PaidSourceMatrixAudit.id),
            func.sum(case((PaidSourceMatrixAudit.failure_code.is_(None), 1), else_=0)),
        )
        .filter(
            PaidSourceMatrixAudit.source_id == source_id,
            PaidSourceMatrixAudit.created_at >= cutoff,
        )
        .one()
    )
    audit.success_rate_7d = float(successful or 0) / max(1, int(total or 0))
    db.commit()
    db.refresh(audit)
    return audit


def trigger_session_expiration(
    db: Session,
    auth_config_id: str,
    root_cause: str = "MANUAL_TEST_EXPIRATION",
) -> SessionRecoveryAudit:
    """Open a manual session-recovery drill audit."""

    audit = SessionRecoveryAudit(
        id=str(uuid.uuid4()),
        auth_config_id=auth_config_id,
        detected_at=utcnow_naive(),
        root_cause=root_cause,
        status="detected",
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)
    return audit


def ack_session_recovery(db: Session, audit_id: str) -> SessionRecoveryAudit | None:
    audit = db.query(SessionRecoveryAudit).filter(SessionRecoveryAudit.id == audit_id).first()
    if audit and audit.status == "detected":
        audit.acked_at = utcnow_naive()
        audit.status = "acked"
        db.commit()
        db.refresh(audit)
    return audit


def complete_session_recovery(db: Session, audit_id: str) -> SessionRecoveryAudit | None:
    audit = db.query(SessionRecoveryAudit).filter(SessionRecoveryAudit.id == audit_id).first()
    if audit and audit.status in ("detected", "acked"):
        now = utcnow_naive()
        audit.recovered_at = now
        audit.status = "recovered"
        audit.mttr_seconds = max(0.0, (now - audit.detected_at).total_seconds())
        db.commit()
        db.refresh(audit)
    return audit


def run_daily_canary_for_source(
    db: Session,
    source_id: str,
    sample_body: str | None,
    run_date_str: str | None = None,
) -> DailyCanaryRun:
    """Record an idempotent canary result for one source/day.

    The caller must perform the real authenticated fetch.  This service does not
    fabricate a network probe from sample data and is not itself a scheduler.
    """

    run_date = run_date_str or utcnow_naive().strftime("%Y-%m-%d")
    try:
        datetime.strptime(run_date, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("run_date_str must use YYYY-MM-DD") from exc

    is_readable, reason = check_readability(sample_body)
    paywall_detected = reason == "PAYWALL_RESIDUAL_DETECTED"
    status = "success" if is_readable else ("degraded" if paywall_detected else "failed")
    body_len = len(sample_body.strip()) if sample_body else 0
    now = utcnow_naive()

    existing = (
        db.query(DailyCanaryRun)
        .filter(DailyCanaryRun.source_id == source_id, DailyCanaryRun.run_date == run_date)
        .first()
    )
    if existing is not None:
        same_result = (
            existing.status == status
            and int(existing.body_length or 0) == body_len
            and bool(existing.paywall_residual_detected) == paywall_detected
            and existing.error_message == reason
        )
        if not same_result:
            raise ValueError(f"Daily canary result for source {source_id} on {run_date} is immutable")
        return existing

    canary_run = DailyCanaryRun(
        id=str(uuid.uuid4()),
        source_id=source_id,
        run_date=run_date,
        status=status,
        body_length=body_len,
        paywall_residual_detected=paywall_detected,
        error_message=reason,
        created_at=now,
    )
    try:
        with db.begin_nested():
            db.add(canary_run)
            db.flush()
    except IntegrityError as exc:
        concurrent = (
            db.query(DailyCanaryRun)
            .filter(DailyCanaryRun.source_id == source_id, DailyCanaryRun.run_date == run_date)
            .one()
        )
        same_result = (
            concurrent.status == status
            and int(concurrent.body_length or 0) == body_len
            and bool(concurrent.paywall_residual_detected) == paywall_detected
            and concurrent.error_message == reason
        )
        if not same_result:
            raise ValueError(f"Daily canary result for source {source_id} on {run_date} is immutable") from exc
        return concurrent
    db.commit()
    db.refresh(canary_run)
    return canary_run
