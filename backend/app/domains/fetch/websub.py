"""WebSub hub verification, signature checks, replay protection, and fetch-job fan-in."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta
from urllib.parse import urlsplit
import uuid
import xml.etree.ElementTree as ET

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import FetchJob, Source, WebSubDelivery, WebSubSubscription
from app.platform.security.encryption import encrypt_string, decrypt_string
from app.utils.datetime import utcnow_naive


def _validate_http_url(value: str, field: str) -> str:
    raw = str(value or "").strip()
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{field} must be an absolute http(s) URL")
    if parsed.username or parsed.password:
        raise ValueError(f"{field} must not contain credentials")
    return raw


def _parse_feed_items(body: bytes) -> list[dict[str, str]]:
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise ValueError("WebSub payload is not valid XML") from exc
    items: list[dict[str, str]] = []
    for node in root.iter():
        if not str(node.tag).lower().endswith(("item", "entry")):
            continue
        values: dict[str, str] = {}
        for child in list(node):
            tag = str(child.tag).split("}")[-1].lower()
            text = (child.text or "").strip()
            if tag in {"title", "id", "published", "updated", "summary", "description"} and text:
                values[tag] = text[:5_000]
            if tag == "link":
                href = child.attrib.get("href") or text
                if href:
                    values["url"] = href[:2_000]
        if values:
            items.append(values)
    return items[:100]


def create_subscription(
    db: Session,
    *,
    source_id: str,
    hub_url: str,
    topic_url: str,
    callback_base_path: str = "/api/websub/callback",
) -> tuple[WebSubSubscription, str, str]:
    source = db.query(Source).filter(Source.id == source_id).first()
    if source is None:
        raise ValueError(f"Source {source_id} not found")
    hub = _validate_http_url(hub_url, "hub_url")
    topic = _validate_http_url(topic_url, "topic_url")
    verify_token = secrets.token_urlsafe(24)
    secret = secrets.token_urlsafe(32)
    subscription_id = str(uuid.uuid4())
    subscription = WebSubSubscription(
        id=subscription_id,
        source_id=str(source.id),
        hub_url=hub,
        topic_url=topic,
        callback_path=f"{callback_base_path.rstrip('/')}/{subscription_id}",
        verify_token_hash=hashlib.sha256(verify_token.encode()).hexdigest(),
        secret_encrypted=encrypt_string(secret),
        status="pending",
        created_at=utcnow_naive(),
    )
    db.add(subscription)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ValueError("WebSub subscription for this source/topic already exists") from exc
    db.refresh(subscription)
    return subscription, verify_token, secret


def verify_subscription(
    db: Session,
    *,
    subscription_id: str,
    mode: str,
    topic: str,
    challenge: str,
    verify_token: str,
    lease_seconds: int = 86_400,
) -> WebSubSubscription:
    subscription = db.query(WebSubSubscription).filter(WebSubSubscription.id == subscription_id).first()
    if subscription is None:
        raise ValueError("WebSub subscription not found")
    if mode not in {"subscribe", "unsubscribe"}:
        raise ValueError("hub.mode must be subscribe or unsubscribe")
    if topic != subscription.topic_url:
        raise ValueError("WebSub topic does not match the bound source")
    expected = hashlib.sha256(str(verify_token or "").encode()).hexdigest()
    if not hmac.compare_digest(expected, subscription.verify_token_hash):
        raise ValueError("WebSub verification token is invalid")
    subscription.status = "active" if mode == "subscribe" else "unsubscribed"
    subscription.last_verified_at = utcnow_naive()  # noqa: V101
    subscription.lease_expires_at = utcnow_naive() + timedelta(seconds=max(60, min(int(lease_seconds), 2_592_000)))
    db.commit()
    db.refresh(subscription)
    return subscription


def _verify_signature(subscription: WebSubSubscription, body: bytes, signature: str | None) -> bool:
    if not signature:
        return False
    algorithm, _, received = signature.partition("=")
    if algorithm not in {"sha1", "sha256"} or not received:
        return False
    digest = hashlib.sha1 if algorithm == "sha1" else hashlib.sha256
    secret = decrypt_string(subscription.secret_encrypted).encode()
    expected = hmac.new(secret, body, digest).hexdigest()
    return hmac.compare_digest(expected, received)


def receive_event(
    db: Session,
    *,
    subscription_id: str,
    body: bytes,
    signature: str | None,
) -> dict:
    subscription = db.query(WebSubSubscription).filter(WebSubSubscription.id == subscription_id).first()
    if subscription is None or subscription.status != "active":
        raise ValueError("WebSub subscription is not active")
    if not _verify_signature(subscription, body, signature):
        raise ValueError("WebSub signature verification failed")
    event_hash = hashlib.sha256(body + str(signature).encode()).hexdigest()
    existing = db.query(WebSubDelivery).filter(WebSubDelivery.event_hash == event_hash).first()
    if existing is not None:
        return {"status": "duplicate", "delivery_id": existing.id, "fetch_job_id": existing.fetch_job_id}
    items = _parse_feed_items(body)
    job = FetchJob(
        id=str(uuid.uuid4()),
        job_type="fetch",
        business_key=f"websub:{subscription.id}:{event_hash}",
        source_id=str(subscription.source_id),
        fetch_kind="websub",
        due_window=utcnow_naive(),
        state="pending",
        priority=50,
        payload_schema_version=1,
        payload={"subscription_id": str(subscription.id), "event_hash": event_hash, "items": items},
        attempts=0,
        max_attempts=3,
        not_before=utcnow_naive(),
        enqueued_at=utcnow_naive(),
        created_at=utcnow_naive(),
        updated_at=utcnow_naive(),
    )
    delivery = WebSubDelivery(
        id=str(uuid.uuid4()),
        subscription_id=str(subscription.id),
        event_hash=event_hash,
        payload_checksum=hashlib.sha256(body).hexdigest(),
        item_count=str(len(items)),
        status="accepted",
        fetch_job_id=str(job.id),
        received_at=utcnow_naive(),
    )
    db.add_all([job, delivery])
    subscription.last_event_at = utcnow_naive()  # noqa: V101
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ValueError("WebSub event replay detected") from exc
    return {"status": "accepted", "delivery_id": delivery.id, "fetch_job_id": job.id, "item_count": len(items)}
