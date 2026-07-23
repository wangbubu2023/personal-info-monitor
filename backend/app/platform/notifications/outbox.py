"""Transactional notification outbox and auditable delivery ledger."""

from __future__ import annotations

import os
from time import perf_counter
from datetime import timedelta
import uuid

from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.reliable_execution import NotificationDelivery, OutboxEvent
from app.platform.observability.logger import get_logger
from app.platform.observability.metrics import reliability_metrics
from app.platform.persistence.database import SessionLocal
from app.platform.persistence.lineage import add_lineage_edge
from app.utils.datetime import utcnow_naive

logger = get_logger(__name__)


def email_delivery_key(
    recipient: str,
    subject: str,
    html_body: str = "",
    idempotency_key: str | None = None,
) -> str:
    if idempotency_key:
        return str(idempotency_key)
    return f"email:{uuid.uuid4().hex}"


def enqueue_email(
    recipient: str,
    subject: str,
    html_body: str,
    *,
    from_email: str | None = None,
    aggregate_type: str = "notification",
    aggregate_id: str = "local",
    idempotency_key: str | None = None,
    session: Session | None = None,
) -> str:
    """Persist an email command, participating in a caller transaction when supplied."""
    key = email_delivery_key(recipient, subject, html_body, idempotency_key)
    owns_session = session is None
    db = session or SessionLocal()
    try:
        existing = db.query(OutboxEvent).filter(OutboxEvent.idempotency_key == key).first()
        if existing is not None:
            return str(existing.id)
        event = OutboxEvent(
            event_type="notification.email",
            aggregate_type=str(aggregate_type),
            aggregate_id=str(aggregate_id),
            payload_schema_version=1,
            payload={
                "recipient": str(recipient),
                "subject": str(subject),
                "html_body": str(html_body),
                "from_email": from_email,
            },
            idempotency_key=key,
            state="pending",
            available_at=utcnow_naive(),
        )
        db.add(event)
        try:
            if owns_session:
                db.commit()
            else:
                db.flush()
        except IntegrityError:
            db.rollback()
            existing = db.query(OutboxEvent).filter(OutboxEvent.idempotency_key == key).one()
            return str(existing.id)
        return str(event.id)
    finally:
        if owns_session:
            db.close()


def _claim_event(event_id: str | None = None, *, lease_seconds: int = 120) -> tuple[str, str] | None:
    now = utcnow_naive()
    token = uuid.uuid4().hex
    owner = f"outbox:{os.getpid()}"
    db = SessionLocal()
    try:
        eligible = or_(
            and_(
                OutboxEvent.state.in_(["pending", "retry_wait"]),
                OutboxEvent.available_at <= now,
            ),
            and_(
                OutboxEvent.state == "delivering",
                OutboxEvent.lease_expires_at.is_not(None),
                OutboxEvent.lease_expires_at <= now,
            ),
        )
        query = db.query(OutboxEvent).filter(eligible)
        if event_id is not None:
            query = query.filter(OutboxEvent.id == event_id)
        row = query.order_by(OutboxEvent.available_at.asc(), OutboxEvent.created_at.asc()).first()
        if row is None:
            return None
        changed = (
            db.query(OutboxEvent)
            .filter(
                OutboxEvent.id == row.id,
                eligible,
            )
            .update(
                {
                    OutboxEvent.state: "delivering",
                    OutboxEvent.locked_by: owner,
                    OutboxEvent.lease_token: token,
                    OutboxEvent.lease_expires_at: now + timedelta(seconds=max(10, int(lease_seconds))),
                    OutboxEvent.attempt: OutboxEvent.attempt + 1,
                    OutboxEvent.updated_at: now,
                },
                synchronize_session=False,
            )
        )
        if changed != 1:
            db.rollback()
            return None
        db.commit()
        return str(row.id), token
    finally:
        db.close()


async def dispatch_outbox_event(event_id: str | None = None) -> bool:
    claimed = _claim_event(event_id)
    if claimed is None:
        if event_id is None:
            return False
        db = SessionLocal()
        try:
            existing = db.query(OutboxEvent).filter(OutboxEvent.id == event_id).first()
            return existing is not None and existing.state == "delivered"
        finally:
            db.close()
    claimed_id, token = claimed
    db = SessionLocal()
    try:
        event = db.query(OutboxEvent).filter(OutboxEvent.id == claimed_id).one()
        payload = event.payload if isinstance(event.payload, dict) else {}
        delivery_key = f"{event.idempotency_key}:smtp"
        delivery = db.query(NotificationDelivery).filter(
            NotificationDelivery.delivery_key == delivery_key
        ).first()
        if delivery is None:
            delivery = NotificationDelivery(
                outbox_id=event.id,
                channel="email",
                recipient_ref=str(payload.get("recipient") or ""),
                delivery_key=delivery_key,
                provider="smtp",
                state="delivering",
                attempt=int(event.attempt or 0),
            )
            db.add(delivery)
            db.commit()
        elif delivery.state == "delivered":
            event.state = "delivered"
            event.delivered_at = delivery.delivered_at or utcnow_naive()
            event.locked_by = None
            event.lease_token = None
            event.lease_expires_at = None
            db.commit()
            return True
        else:
            delivery.state = "delivering"
            delivery.attempt = int(event.attempt or 0)
            db.commit()
    finally:
        db.close()

    from app.platform.notifications.smtp import _send_email_direct

    started = perf_counter()
    error: str | None = None
    try:
        sent = await _send_email_direct(
            str(payload.get("recipient") or ""),
            str(payload.get("subject") or ""),
            str(payload.get("html_body") or ""),
            payload.get("from_email"),
        )
        if not sent:
            error = "provider_not_configured_or_failed"
    except Exception as exc:  # noqa: BLE001 - convert provider failure to ledger state
        sent = False
        error = str(exc)
    latency_ms = int((perf_counter() - started) * 1000)
    now = utcnow_naive()

    db = SessionLocal()
    try:
        event = db.query(OutboxEvent).filter(
            OutboxEvent.id == claimed_id,
            OutboxEvent.lease_token == token,
        ).first()
        if event is None:
            return False
        delivery = db.query(NotificationDelivery).filter(
            NotificationDelivery.delivery_key == delivery_key
        ).one()
        delivery.latency_ms = latency_ms
        reliability_metrics.record("outbox_delivery_latency_ms", latency_ms)
        delivery.response_excerpt = (error or "accepted")[:1000]
        delivery.updated_at = now
        if sent:
            event.state = "delivered"
            event.delivered_at = now
            event.last_error = None
            delivery.state = "delivered"
            delivery.delivered_at = now
            delivery.next_retry_at = None
            reliability_metrics.record("outbox_delivered")
        else:
            retryable = int(event.attempt or 0) < int(event.max_attempts or 5)
            event.state = "retry_wait" if retryable else "dead"
            event.last_error = (error or "delivery failed")[:4000]
            event.available_at = now + timedelta(
                seconds=min(3600, 30 * (2 ** max(0, int(event.attempt or 1) - 1)))
            )
            delivery.state = "retry_wait" if retryable else "dead"
            delivery.next_retry_at = event.available_at if retryable else None
            reliability_metrics.record("outbox_retry" if retryable else "outbox_dead")
        event.locked_by = None
        event.lease_token = None
        event.lease_expires_at = None
        event.updated_at = now
        db.commit()
        if sent:
            add_lineage_edge(
                from_type=event.aggregate_type,
                from_id=event.aggregate_id,
                to_type="outbox",
                to_id=str(event.id),
                relation="emitted",
            )
            add_lineage_edge(
                from_type="outbox",
                from_id=str(event.id),
                to_type="delivery",
                to_id=str(delivery.id),
                relation="delivered_as",
            )
        return bool(sent)
    finally:
        db.close()


async def dispatch_pending_outbox(*, limit: int = 100) -> dict[str, int]:
    delivered = failed = 0
    db = SessionLocal()
    try:
        event_ids = [
            str(row.id)
            for row in (
                db.query(OutboxEvent)
                .filter(
                    or_(
                        and_(
                            OutboxEvent.state.in_(["pending", "retry_wait"]),
                            OutboxEvent.available_at <= utcnow_naive(),
                        ),
                        and_(
                            OutboxEvent.state == "delivering",
                            OutboxEvent.lease_expires_at.is_not(None),
                            OutboxEvent.lease_expires_at <= utcnow_naive(),
                        ),
                    ),
                )
                .order_by(OutboxEvent.available_at.asc(), OutboxEvent.created_at.asc())
                .limit(max(1, int(limit)))
                .all()
            )
        ]
    finally:
        db.close()
    for event_id in event_ids:
        if await dispatch_outbox_event(event_id):
            delivered += 1
        else:
            failed += 1
    return {"delivered": delivered, "failed": failed}


__all__ = [
    "dispatch_outbox_event",
    "dispatch_pending_outbox",
    "email_delivery_key",
    "enqueue_email",
]
