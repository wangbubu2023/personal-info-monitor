"""Local Capture token, origin, and replay controls.

The browser-side worker is not trusted to choose its own allowlist.  Tokens are
short-lived, nonce-bearing, bound to a canonical origin, and signed with the
runtime encryption secret.  A consumed token is recorded under a database
unique constraint so retries/replays fail closed across processes.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from urllib.parse import urlsplit
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domains.ingest.storage import StorageStage
from app.models import Content
from app.models.auth_assistant import AuthAssistantDevice, AuthAssistantDeviceStatus
from app.models.paid_matrix import LocalCaptureAudit
from app.models.source import Source
from app.platform.config.settings import get_settings
from app.utils.logger import get_logger
from app.utils.datetime import utcnow_naive
from app.utils.text import strip_html_tags

logger = get_logger(__name__)

TASK_TOKEN_TTL_SECONDS = 300
TASK_TOKEN_FUTURE_SKEW_SECONDS = 30
MAX_READER_DOC_TITLE_CHARS = 512
MAX_READER_DOC_BODY_CHARS = 2_000_000
_TOKEN_VERSION = "v1"
_TOKEN_CONTEXT = b"pim-local-capture-task-token-v1"


def _canonical_origin(origin_url: str) -> str:
    parsed = urlsplit(str(origin_url or "").strip())
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower().rstrip(".")
    if scheme not in {"http", "https"} or not host:
        raise ValueError("origin_url must be an absolute http(s) URL")
    port = parsed.port
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    authority = host if port is None or default_port else f"{host}:{port}"
    return f"{scheme}://{authority}"


def _capture_secret() -> bytes:
    secret = str(get_settings().encryption_key or "").encode("utf-8")
    if len(secret) < 16:
        raise RuntimeError("Local Capture signing secret is not configured")
    return hmac.new(secret, _TOKEN_CONTEXT, hashlib.sha256).digest()


def _token_message(*, created_ts: int, nonce: str, device_id: str, origin: str) -> bytes:
    return f"{_TOKEN_VERSION}\n{created_ts}\n{nonce}\n{device_id}\n{origin}".encode("utf-8")


def generate_task_token(device_id: str, origin_url: str) -> str:
    """Generate a nonce-bearing token valid for five minutes."""

    device = str(device_id or "").strip()
    if not device:
        raise ValueError("device_id is required")
    origin = _canonical_origin(origin_url)
    created_ts = int(utcnow_naive().timestamp())
    nonce = secrets.token_urlsafe(18)
    signature = hmac.new(
        _capture_secret(),
        _token_message(created_ts=created_ts, nonce=nonce, device_id=device, origin=origin),
        hashlib.sha256,
    ).hexdigest()
    return f"{_TOKEN_VERSION}.{created_ts}.{nonce}.{signature}"


def verify_task_token(token: str, device_id: str, origin_url: str) -> bool:
    """Verify format, age, origin/device binding, and HMAC signature."""

    parts = str(token or "").split(".", 3)
    if len(parts) != 4 or parts[0] != _TOKEN_VERSION:
        return False
    _version, ts_str, nonce, client_hash = parts
    try:
        created_ts = int(ts_str)
        origin = _canonical_origin(origin_url)
    except (TypeError, ValueError):
        return False
    device = str(device_id or "").strip()
    if not device or not nonce or not client_hash:
        return False

    now_ts = int(utcnow_naive().timestamp())
    age = now_ts - created_ts
    if age < -TASK_TOKEN_FUTURE_SKEW_SECONDS or age > TASK_TOKEN_TTL_SECONDS:
        return False

    expected_hash = hmac.new(
        _capture_secret(),
        _token_message(created_ts=created_ts, nonce=nonce, device_id=device, origin=origin),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected_hash, client_hash)


def _allowed_capture_hosts(db: Session) -> set[str]:
    """Return server-configured hosts eligible for Local Capture.

    Only enabled authenticated/paid website sources participate.  This keeps the
    policy on the PIM side instead of accepting an allowlist from the submitter.
    """

    rows = db.query(Source).filter(Source.enabled.is_(True)).all()
    hosts: set[str] = set()
    for source in rows:
        metadata = source.metadata_ if isinstance(source.metadata_, dict) else {}
        paid = metadata.get("paid_source") if isinstance(metadata.get("paid_source"), dict) else {}
        if not source.auth_required and not bool(paid.get("enabled")):
            continue
        try:
            host = urlsplit(str(source.url or "")).hostname
        except ValueError:
            host = None
        if host:
            hosts.add(host.lower().rstrip("."))
    return hosts


def verify_origin_allowlist(origin_url: str, allowlist: list[str] | set[str] | None = None) -> bool:
    """Match an origin host exactly or as a subdomain of a configured host."""

    if not allowlist:
        return False
    try:
        host = urlsplit(_canonical_origin(origin_url)).hostname or ""
    except ValueError:
        return False
    for raw_allowed in allowlist:
        value = str(raw_allowed or "").strip().lower().rstrip(".")
        if not value:
            continue
        try:
            allowed_host = (urlsplit(value).hostname if "://" in value else value) or ""
        except ValueError:
            continue
        allowed_host = allowed_host.lower().rstrip(".")
        if host == allowed_host or host.endswith(f".{allowed_host}"):
            return True
    return False


def _require_active_device(db: Session, device_id: str) -> AuthAssistantDevice:
    device = (
        db.query(AuthAssistantDevice)
        .filter(
            AuthAssistantDevice.id == str(device_id or "").strip(),
            AuthAssistantDevice.status == AuthAssistantDeviceStatus.ACTIVE,
            AuthAssistantDevice.revoked_at.is_(None),
        )
        .first()
    )
    if device is None:
        raise ValueError("Local Capture device is not paired or has been revoked")
    return device


def _capture_source(db: Session, origin_url: str) -> Source:
    candidates = db.query(Source).filter(Source.enabled.is_(True)).all()
    allowed = _allowed_capture_hosts(db)
    for source in candidates:
        if not source.auth_required:
            metadata = source.metadata_ if isinstance(source.metadata_, dict) else {}
            paid = metadata.get("paid_source") if isinstance(metadata.get("paid_source"), dict) else {}
            if not bool(paid.get("enabled")):
                continue
        if verify_origin_allowlist(origin_url, allowed) and verify_origin_allowlist(
            origin_url,
            [urlsplit(str(source.url)).hostname or ""],
        ):
            return source
    raise ValueError("Origin URL is not bound to an enabled capture source")


def issue_local_capture_task_token(db: Session, device_id: str, origin_url: str) -> str:
    """Issue a token only for a server-configured capture origin."""

    _require_active_device(db, device_id)
    if not verify_origin_allowlist(origin_url, _allowed_capture_hosts(db)):
        raise ValueError("Origin URL is not configured for Local Capture")
    return generate_task_token(device_id, origin_url)


def process_local_capture(
    db: Session,
    device_id: str,
    task_token: str,
    origin_url: str,
    reader_doc_title: str,
    reader_doc_body: str,
) -> LocalCaptureAudit:
    """Validate, persist, audit, and enqueue a purified ReaderDocument.

    The browser remains the only place that can read local cookies.  The
    server receives the user-authorized ReaderDocument body, stores it through
    the normal StorageStage, and creates a durable finish job after the
    transaction commits.
    """

    _require_active_device(db, device_id)
    allowed_hosts = _allowed_capture_hosts(db)
    if not verify_origin_allowlist(origin_url, allowed_hosts):
        raise ValueError("Origin URL is not configured for Local Capture")
    if not verify_task_token(task_token, device_id, origin_url):
        raise ValueError("Invalid or expired task token for local capture")
    token_hash = hashlib.sha256(task_token.encode("utf-8")).hexdigest()
    if db.query(LocalCaptureAudit).filter(LocalCaptureAudit.task_token_hash == token_hash).first() is not None:
        raise ValueError("Local Capture task token has already been consumed")

    raw_title = str(reader_doc_title or "")
    raw_body = str(reader_doc_body or "")
    if len(raw_title) > MAX_READER_DOC_TITLE_CHARS:
        raise ValueError(
            f"ReaderDocument title exceeds {MAX_READER_DOC_TITLE_CHARS} characters"
        )
    if len(raw_body) > MAX_READER_DOC_BODY_CHARS:
        raise ValueError(
            f"ReaderDocument body exceeds {MAX_READER_DOC_BODY_CHARS} characters"
        )
    title = raw_title.strip()
    body = strip_html_tags(raw_body).strip()
    if not title or not body:
        raise ValueError("ReaderDocument title and body are required")

    canonical_origin = _canonical_origin(origin_url)
    source = _capture_source(db, origin_url)
    content_digest = hashlib.sha256()
    for part in (canonical_origin, "\n", title, "\n", body):
        content_digest.update(part.encode("utf-8"))
    checksum = content_digest.hexdigest()
    content = Content(
        id=str(uuid.uuid4()),
        source_id=str(source.id),
        external_id=f"local-capture:{checksum}",
        title=title,
        summary=body[:2_000],
        original_url=str(origin_url).strip(),
        full_content=body,
        content_type="website",
        fetched_at=utcnow_naive(),
        metadata_={
            "capture_mode": "local_reader_document",
            "capture_device_id": str(device_id).strip(),
            "capture_origin": canonical_origin,
            "reader_doc_checksum": checksum,
            "fetch_acceptance": "accepted",
            "fulltext_status": "full",
            "article_fulltext": True,
        },
    )
    storage_result = StorageStage.execute(db, [content])
    if storage_result.failed_count:
        db.rollback()
        raise ValueError(storage_result.failed_items[0].message)
    content_id = storage_result.saved_ids[0] if storage_result.saved_ids else (
        storage_result.updated_ids[0] if storage_result.updated_ids else None
    )
    if not content_id:
        db.rollback()
        raise ValueError("Local Capture content was not persisted")
    audit = LocalCaptureAudit(
        id=str(uuid.uuid4()),
        device_id=str(device_id).strip(),
        task_token_hash=token_hash,
        source_id=str(source.id),
        content_id=str(content_id),
        origin_url=canonical_origin,
        reader_doc_checksum=checksum,
        body_length=len(body),
        ingest_status="stored",
        created_at=utcnow_naive(),
    )
    db.add(audit)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ValueError("Local Capture task token has already been consumed") from exc
    db.refresh(audit)
    try:
        from app.platform.workers.postprocess_jobs import ensure_postprocess_jobs

        ensure_postprocess_jobs([(str(content_id), "local-capture")])
    except Exception as exc:  # noqa: BLE001 - durable audit/content already committed
        # The regular startup sweep can recover this enqueue failure. Keep the
        # capture visible and truthful instead of losing the user's document.
        audit.ingest_status = "stored_enqueue_deferred"
        db.commit()
        logger.warning("Local Capture postprocess enqueue deferred for %s: %s", content_id, exc)
    return audit
