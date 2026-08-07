"""Durable daily paid-source Canary runner and health history."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable
import uuid

from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.domains.fetch.paid_matrix import record_paid_source_result, run_daily_canary_for_source
from app.models import Source, SourceHealthSnapshot
from app.platform.persistence.database import SessionLocal
from app.utils.datetime import utcnow_naive
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class CanaryProbeResult:
    body: str | None
    http_status: int = 200
    login_required: bool = False
    metadata: dict[str, Any] | None = None


Probe = Callable[[Session, Source], CanaryProbeResult | dict[str, Any] | Awaitable[CanaryProbeResult | dict[str, Any]]]


async def _default_probe(db: Session, source: Source) -> CanaryProbeResult:
    """Fetch one real source sample through the existing collector boundary."""

    from app.domains.fetch.collector_stage import CollectorStage

    raw_items, warning, primary = await CollectorStage.execute(db, source)
    first = raw_items[0] if raw_items else {}
    body = first.get("full_content") or first.get("content") or first.get("summary")
    status = 200
    if primary and primary[0].startswith("HTTP_"):
        try:
            status = int(primary[0].removeprefix("HTTP_"))
        except ValueError:
            status = 503
    return CanaryProbeResult(
        body=str(body) if body else None,
        http_status=status,
        login_required=bool(warning and any(term in warning.lower() for term in ("login", "登录", "session", "会话"))),
        metadata={"warning": warning, "primary_warning": primary[0] if primary else None},
    )


def _normalize_probe(value: CanaryProbeResult | dict[str, Any]) -> CanaryProbeResult:
    if isinstance(value, CanaryProbeResult):
        return value
    if not isinstance(value, dict):
        raise ValueError("Canary probe must return CanaryProbeResult or object")
    return CanaryProbeResult(
        body=value.get("body") or value.get("sample_body"),
        http_status=int(value.get("http_status", 200)),
        login_required=bool(value.get("login_required", False)),
        metadata=value.get("metadata") if isinstance(value.get("metadata"), dict) else {},
    )


def _is_paid_source(source: Source) -> bool:
    metadata = source.metadata_ if isinstance(source.metadata_, dict) else {}
    paid = metadata.get("paid_source") if isinstance(metadata.get("paid_source"), dict) else {}
    return bool(source.auth_required or paid.get("enabled"))


def _enqueue_unhealthy_alert(db: Session, source: Source, canary, reason: str | None) -> None:
    from app.domains.notifications.webhooks import enqueue_webhook_event

    enqueue_webhook_event(
        db,
        event_type="source.unhealthy",
        aggregate_type="source",
        aggregate_id=str(source.id),
        payload={
            "source_id": str(source.id),
            "source_name": source.name,
            "run_date": canary.run_date,
            "status": canary.status,
            "failure_code": canary.error_message,
            "reason": reason,
        },
    )


async def run_daily_paid_source_canaries(
    *,
    run_date: str | None = None,
    probe: Probe | None = None,
    session_factory=SessionLocal,
) -> dict[str, int | list[str]]:
    """Run one idempotent probe per enabled paid/authenticated source.

    ``probe`` is injectable for deterministic conformance tests; production
    uses the real collector and therefore does not turn caller-provided sample
    text into a fake health result.
    """

    db = session_factory()
    attempted = succeeded = failed = 0
    source_ids: list[str] = []
    try:
        sources = [source for source in db.query(Source).filter(Source.enabled.is_(True)).all() if _is_paid_source(source)]
        for source in sources:
            attempted += 1
            source_ids.append(str(source.id))
            try:
                raw_probe = (probe or _default_probe)(db, source)
                result = _normalize_probe(await raw_probe if inspect.isawaitable(raw_probe) else raw_probe)
                canary = run_daily_canary_for_source(
                    db,
                    source_id=str(source.id),
                    sample_body=result.body,
                    run_date_str=run_date,
                )
                record_paid_source_result(
                    db,
                    source_id=str(source.id),
                    body_text=result.body,
                    discovery_url=source.url,
                    validation_url=source.url,
                    http_status=result.http_status,
                )
                now = utcnow_naive()
                db.add(
                    SourceHealthSnapshot(
                        id=str(uuid.uuid4()),
                        source_id=str(source.id),
                        check_type="daily_canary",
                        status=canary.status,
                        http_status=result.http_status,
                        body_length=len(result.body.strip()) if result.body else 0,
                        login_required=result.login_required,
                        paywall_residual_detected=bool(canary.paywall_residual_detected),
                        selector_quality=min(1.0, len(result.body.strip()) / 1000) if result.body else 0.0,
                        error_message=canary.error_message,
                        metadata_=result.metadata or {},
                        observed_at=now,
                    )
                )
                if canary.status == "success":
                    succeeded += 1
                else:
                    failed += 1
                    _enqueue_unhealthy_alert(db, source, canary, canary.error_message)
                db.commit()
            except Exception as exc:  # noqa: BLE001 - one source cannot block the matrix
                db.rollback()
                failed += 1
                logger.exception("Daily Canary failed for source %s", source.id)
                try:
                    db.add(
                        SourceHealthSnapshot(
                            id=str(uuid.uuid4()),
                            source_id=str(source.id),
                            check_type="daily_canary",
                            status="failed",
                            error_message=str(exc)[:500],
                            metadata_={"exception": exc.__class__.__name__},
                            observed_at=utcnow_naive(),
                        )
                    )
                    db.commit()
                except (SQLAlchemyError, ValueError) as recovery_exc:
                    db.rollback()
                    logger.warning("Could not persist failed Canary health snapshot for %s: %s", source.id, recovery_exc)
        return {"attempted": attempted, "succeeded": succeeded, "failed": failed, "source_ids": source_ids}
    finally:
        db.close()


def source_health_history(db: Session, source_id: str, *, days: int = 7) -> list[dict[str, Any]]:
    cutoff = utcnow_naive() - timedelta(days=max(1, int(days)))
    rows = (
        db.query(SourceHealthSnapshot)
        .filter(SourceHealthSnapshot.source_id == source_id, SourceHealthSnapshot.observed_at >= cutoff)
        .order_by(SourceHealthSnapshot.observed_at.desc())
        .all()
    )
    return [
        {
            "id": row.id,
            "source_id": row.source_id,
            "check_type": row.check_type,
            "status": row.status,
            "http_status": row.http_status,
            "body_length": row.body_length,
            "login_required": row.login_required,
            "paywall_residual_detected": row.paywall_residual_detected,
            "selector_quality": row.selector_quality,
            "error_message": row.error_message,
            "metadata": row.metadata_,
            "observed_at": row.observed_at.isoformat() if row.observed_at else None,
        }
        for row in rows
    ]
