"""Webhook subscription and transactional Outbox fan-out."""

from __future__ import annotations

import ipaddress
import secrets
from urllib.parse import urlsplit
import uuid

from sqlalchemy.orm import Session

from app.models import OutboxEvent, WebhookSubscription
from app.platform.security.encryption import encrypt_string
from app.utils.datetime import utcnow_naive


def _validate_target(value: str) -> str:
    raw = str(value or "").strip()
    parsed = urlsplit(raw)
    host = parsed.hostname
    if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
        raise ValueError("target_url must be an absolute http(s) URL without credentials")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address and (address.is_private or address.is_loopback or address.is_link_local or address.is_reserved):
        raise ValueError("target_url must not point to a private or loopback address")
    return raw


def create_webhook_subscription(
    db: Session,
    *,
    target_url: str,
    event_filters: list[str] | None = None,
    secret: str | None = None,
) -> tuple[WebhookSubscription, str]:
    target = _validate_target(target_url)
    plaintext_secret = secret or secrets.token_urlsafe(32)
    if len(plaintext_secret) < 24:
        raise ValueError("webhook secret must contain at least 24 characters")
    subscription = WebhookSubscription(
        id=str(uuid.uuid4()),
        target_url=target,
        event_filters=sorted({str(item).strip() for item in (event_filters or []) if str(item).strip()}),
        secret_encrypted=encrypt_string(plaintext_secret),
        secret_key_version="v1",
        active=True,
        created_at=utcnow_naive(),
        updated_at=utcnow_naive(),
    )
    db.add(subscription)
    db.commit()
    db.refresh(subscription)
    return subscription, plaintext_secret


def list_webhooks(db: Session) -> list[dict]:
    return [
        {
            "id": row.id,
            "target_url": row.target_url,
            "event_filters": row.event_filters,
            "active": row.active,
            "secret_key_version": row.secret_key_version,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in db.query(WebhookSubscription).order_by(WebhookSubscription.created_at.desc()).all()
    ]


def set_webhook_active(db: Session, subscription_id: str, active: bool) -> WebhookSubscription:
    row = db.query(WebhookSubscription).filter(WebhookSubscription.id == subscription_id).first()
    if row is None:
        raise ValueError("Webhook subscription not found")
    row.active = bool(active)
    row.updated_at = utcnow_naive()
    db.commit()
    db.refresh(row)
    return row


def enqueue_webhook_event(
    db: Session,
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    payload: dict,
) -> int:
    rows = db.query(WebhookSubscription).filter(WebhookSubscription.active.is_(True)).all()
    created = 0
    for subscription in rows:
        filters = {str(item) for item in (subscription.event_filters or [])}
        if filters and event_type not in filters:
            continue
        key = f"webhook:{subscription.id}:{event_type}:{aggregate_id}"
        if db.query(OutboxEvent).filter(OutboxEvent.idempotency_key == key).first():
            continue
        db.add(
            OutboxEvent(
                id=str(uuid.uuid4()),
                event_type="integration.webhook",
                aggregate_type=aggregate_type,
                aggregate_id=str(aggregate_id),
                payload_schema_version=1,
                payload={
                    "subscription_id": str(subscription.id),
                    "target_url": subscription.target_url,
                    "secret_encrypted": subscription.secret_encrypted,
                    "event_type": event_type,
                    "data": payload,
                },
                idempotency_key=key,
                state="pending",
                available_at=utcnow_naive(),
            )
        )
        created += 1
    if created:
        db.commit()
    return created
