"""Short-lived access tokens and rotating refresh families."""

from __future__ import annotations

from datetime import timedelta
import hashlib
import secrets
import uuid

from sqlalchemy.orm import Session

from app.models import AuditActor, IdentityDevice, IdentitySession, IdentityUser
from app.utils.datetime import utcnow_naive

ACCESS_TTL_SECONDS = 10 * 60
REFRESH_TTL_SECONDS = 30 * 24 * 60 * 60


def _hash(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _audit(db: Session, *, tenant_id: str, actor_type: str, actor_id: str, action: str, target_type: str | None = None, target_id: str | None = None, metadata: dict | None = None) -> None:
    db.add(
        AuditActor(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            metadata_=metadata or {},
            created_at=utcnow_naive(),
        )
    )


def ensure_user_device(db: Session, *, subject: str, tenant_id: str = "default", email: str | None = None, device_name: str = "local") -> tuple[IdentityUser, IdentityDevice]:
    user = db.query(IdentityUser).filter(IdentityUser.tenant_id == tenant_id, IdentityUser.subject == subject).first()
    if user is None:
        user = IdentityUser(id=str(uuid.uuid4()), tenant_id=tenant_id, subject=subject, email=email, created_at=utcnow_naive())
        db.add(user)
        db.flush()
    device = IdentityDevice(
        id=str(uuid.uuid4()),
        user_id=str(user.id),
        tenant_id=tenant_id,
        device_key=secrets.token_urlsafe(24),
        name=device_name[:255],
        status="active",
        created_at=utcnow_naive(),
    )
    db.add(device)
    db.commit()
    db.refresh(user)
    db.refresh(device)
    return user, device


def issue_session(db: Session, *, user_id: str, device_id: str, scopes: list[str] | None = None) -> dict:
    user = db.query(IdentityUser).filter(IdentityUser.id == user_id, IdentityUser.status == "active").first()
    device = db.query(IdentityDevice).filter(IdentityDevice.id == device_id, IdentityDevice.status == "active", IdentityDevice.revoked_at.is_(None)).first()
    if user is None or device is None or str(device.user_id) != str(user.id) or device.tenant_id != user.tenant_id:
        raise ValueError("user/device tenant boundary validation failed")
    now = utcnow_naive()
    access_token = secrets.token_urlsafe(32)
    refresh_token = secrets.token_urlsafe(48)
    session = IdentitySession(
        id=str(uuid.uuid4()),
        user_id=str(user.id),
        device_id=str(device.id),
        tenant_id=user.tenant_id,
        scopes=sorted({str(item).strip() for item in (scopes or []) if str(item).strip()}),
        access_token_hash=_hash(access_token),
        access_expires_at=now + timedelta(seconds=ACCESS_TTL_SECONDS),
        refresh_family_id=uuid.uuid4().hex,
        refresh_token_hash=_hash(refresh_token),
        refresh_expires_at=now + timedelta(seconds=REFRESH_TTL_SECONDS),
        created_at=now,
        last_seen_at=now,
    )
    db.add(session)
    _audit(db, tenant_id=user.tenant_id, actor_type="user", actor_id=str(user.id), action="session.issued", target_type="device", target_id=str(device.id))
    db.commit()
    return {"session_id": session.id, "access_token": access_token, "refresh_token": refresh_token, "access_expires_at": session.access_expires_at.isoformat(), "refresh_expires_at": session.refresh_expires_at.isoformat(), "scopes": session.scopes, "tenant_id": session.tenant_id}


def rotate_refresh_token(db: Session, refresh_token: str) -> dict:
    now = utcnow_naive()
    row = db.query(IdentitySession).filter(IdentitySession.refresh_token_hash == _hash(refresh_token)).first()
    if row is None:
        raise ValueError("refresh token is invalid")
    if row.revoked_at is not None or row.refresh_expires_at <= now:
        raise ValueError("refresh token is expired or revoked")
    if row.refresh_used_at is not None:
        # Reuse detection revokes every session in the family, not only the
        # replayed row. This is the critical refresh-token family invariant.
        db.query(IdentitySession).filter(IdentitySession.refresh_family_id == row.refresh_family_id).update({IdentitySession.revoked_at: now}, synchronize_session=False)
        _audit(db, tenant_id=row.tenant_id, actor_type="security", actor_id=str(row.user_id), action="refresh.reuse_detected", target_type="session", target_id=str(row.id))
        db.commit()
        raise ValueError("refresh token reuse detected; session family revoked")
    row.refresh_used_at = now
    access_token = secrets.token_urlsafe(32)
    replacement = secrets.token_urlsafe(48)
    replacement_row = IdentitySession(
        id=str(uuid.uuid4()),
        user_id=row.user_id,
        device_id=row.device_id,
        tenant_id=row.tenant_id,
        scopes=row.scopes or [],
        access_token_hash=_hash(access_token),
        access_expires_at=now + timedelta(seconds=ACCESS_TTL_SECONDS),
        refresh_family_id=row.refresh_family_id,
        refresh_token_hash=_hash(replacement),
        refresh_expires_at=row.refresh_expires_at,
        rotated_from_id=row.id,
        created_at=now,
        last_seen_at=now,
    )
    db.add(replacement_row)
    _audit(db, tenant_id=row.tenant_id, actor_type="user", actor_id=str(row.user_id), action="session.rotated", target_type="session", target_id=str(replacement_row.id))
    db.commit()
    return {"session_id": replacement_row.id, "access_token": access_token, "refresh_token": replacement, "access_expires_at": replacement_row.access_expires_at.isoformat(), "refresh_expires_at": replacement_row.refresh_expires_at.isoformat(), "scopes": replacement_row.scopes, "tenant_id": replacement_row.tenant_id}


def revoke_device(db: Session, *, device_id: str, tenant_id: str = "default") -> int:
    now = utcnow_naive()
    device = db.query(IdentityDevice).filter(IdentityDevice.id == device_id, IdentityDevice.tenant_id == tenant_id).first()
    if device is None:
        raise ValueError("device not found in tenant")
    device.status = "revoked"
    device.revoked_at = now
    changed = db.query(IdentitySession).filter(IdentitySession.device_id == device_id, IdentitySession.tenant_id == tenant_id, IdentitySession.revoked_at.is_(None)).update({IdentitySession.revoked_at: now}, synchronize_session=False)
    _audit(db, tenant_id=tenant_id, actor_type="operator", actor_id="system", action="device.revoked", target_type="device", target_id=device_id, metadata={"session_count": changed})
    db.commit()
    return int(changed)
