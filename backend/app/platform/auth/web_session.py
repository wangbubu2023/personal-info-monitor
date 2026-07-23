"""Short-lived one-time bootstrap codes and revocable Web sessions."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta

from app.models.web_session import BootstrapCode, WebSession
from app.platform.persistence.database import SessionLocal
from app.utils.datetime import utcnow_naive

SESSION_COOKIE_NAME = "pim_session"
BOOTSTRAP_CODE_TTL_SECONDS = 5 * 60
SESSION_IDLE_SECONDS = 12 * 60 * 60
SESSION_ABSOLUTE_SECONDS = 7 * 24 * 60 * 60


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SessionIssue:
    token: str
    session_id: str
    actor: str


def issue_bootstrap_code(*, actor: str = "local-cli", ttl_seconds: int = BOOTSTRAP_CODE_TTL_SECONDS) -> str:
    code = secrets.token_urlsafe(24)
    now = utcnow_naive()
    db = SessionLocal()
    try:
        db.add(
            BootstrapCode(
                code_hash=_hash(code),
                actor=(actor or "local-cli")[:128],
                expires_at=now + timedelta(seconds=min(BOOTSTRAP_CODE_TTL_SECONDS, max(1, int(ttl_seconds)))),
                created_at=now,
            )
        )
        db.commit()
        return code
    finally:
        db.close()


def exchange_bootstrap_code(code: str) -> SessionIssue | None:
    clean = str(code or "").strip()
    if not clean:
        return None
    now = utcnow_naive()
    db = SessionLocal()
    try:
        row = db.query(BootstrapCode).filter(BootstrapCode.code_hash == _hash(clean)).first()
        if row is None or row.revoked or row.used_at is not None or row.expires_at <= now:
            return None
        actor = str(row.actor)
        claimed = (
            db.query(BootstrapCode)
            .filter(
                BootstrapCode.id == row.id,
                BootstrapCode.used_at.is_(None),
                BootstrapCode.revoked.is_(False),
                BootstrapCode.expires_at > now,
            )
            .update({"used_at": now}, synchronize_session=False)
        )
        if claimed != 1:
            db.rollback()
            return None
        token = secrets.token_urlsafe(48)
        session = WebSession(
            token_hash=_hash(token),
            actor=actor,
            created_at=now,
            last_seen_at=now,
            idle_expires_at=now + timedelta(seconds=SESSION_IDLE_SECONDS),
            absolute_expires_at=now + timedelta(seconds=SESSION_ABSOLUTE_SECONDS),
        )
        db.add(session)
        db.commit()
        return SessionIssue(token=token, session_id=str(session.id), actor=str(session.actor))
    finally:
        db.close()


def validate_web_session(token: str, *, touch: bool = True) -> str | None:
    clean = str(token or "").strip()
    if not clean:
        return None
    now = utcnow_naive()
    db = SessionLocal()
    try:
        row = db.query(WebSession).filter(WebSession.token_hash == _hash(clean)).first()
        if (
            row is None
            or row.revoked_at is not None
            or row.idle_expires_at <= now
            or row.absolute_expires_at <= now
        ):
            return None
        if touch and (now - row.last_seen_at).total_seconds() >= 60:
            row.last_seen_at = now
            row.idle_expires_at = min(
                now + timedelta(seconds=SESSION_IDLE_SECONDS),
                row.absolute_expires_at,
            )
            db.commit()
        return str(row.actor)
    finally:
        db.close()


def revoke_web_session(token: str) -> bool:
    db = SessionLocal()
    try:
        row = db.query(WebSession).filter(WebSession.token_hash == _hash(str(token or ""))).first()
        if row is None:
            return False
        row.revoked_at = utcnow_naive()
        db.commit()
        return True
    finally:
        db.close()


def rotate_web_session(token: str) -> SessionIssue | None:
    now = utcnow_naive()
    db = SessionLocal()
    try:
        row = db.query(WebSession).filter(WebSession.token_hash == _hash(str(token or ""))).first()
        if row is None or row.revoked_at is not None or row.absolute_expires_at <= now:
            return None
        actor = str(row.actor)
        absolute_expires_at = row.absolute_expires_at
        rotated_from_id = str(row.id)
        claimed = (
            db.query(WebSession)
            .filter(WebSession.id == row.id, WebSession.revoked_at.is_(None))
            .update({"revoked_at": now}, synchronize_session=False)
        )
        if claimed != 1:
            db.rollback()
            return None
        replacement = secrets.token_urlsafe(48)
        session = WebSession(
            token_hash=_hash(replacement),
            actor=actor,
            created_at=now,
            last_seen_at=now,
            idle_expires_at=min(now + timedelta(seconds=SESSION_IDLE_SECONDS), absolute_expires_at),
            absolute_expires_at=absolute_expires_at,
            rotated_from_id=rotated_from_id,
        )
        db.add(session)
        db.commit()
        return SessionIssue(replacement, str(session.id), actor)
    finally:
        db.close()


__all__ = [
    "BOOTSTRAP_CODE_TTL_SECONDS",
    "SESSION_COOKIE_NAME",
    "exchange_bootstrap_code",
    "issue_bootstrap_code",
    "revoke_web_session",
    "rotate_web_session",
    "validate_web_session",
]
