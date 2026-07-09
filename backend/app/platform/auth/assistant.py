"""Pairing and device-token helpers for PIM Auth Assistant."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth_assistant import AuthAssistantDevice, AuthAssistantDeviceStatus
from app.utils.datetime import utcnow_naive

_AUTH_ASSISTANT_TOKEN_BYTES = 32


def generate_pairing_token() -> str:
    """Return a short one-time token suitable for copying from PIM Web."""

    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    raw = "".join(secrets.choice(alphabet) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def generate_device_token() -> str:
    """Return a long-lived bearer token for a paired Auth Assistant device."""

    return f"paa_{secrets.token_urlsafe(_AUTH_ASSISTANT_TOKEN_BYTES)}"


def hash_secret(value: str) -> str:
    """Hash a token before storing it."""

    return hashlib.sha256(value.strip().encode("utf-8")).hexdigest()


def token_hint(value: str) -> str:
    """Return a non-sensitive suffix shown in management UI."""

    compact = value.replace("-", "")
    return compact[-4:] if len(compact) >= 4 else compact


def expires_at_from_now(minutes: int) -> datetime:
    return utcnow_naive() + timedelta(minutes=max(1, int(minutes or 1)))


async def require_auth_assistant_device(
    db: AsyncSession,
    authorization: str | None = None,
    x_auth_assistant_token: str | None = None,
) -> AuthAssistantDevice:
    """Validate Auth Assistant bearer token and return the paired device."""

    raw_token = _extract_device_token(authorization, x_auth_assistant_token)
    if not raw_token:
        raise HTTPException(status_code=401, detail="Missing Auth Assistant device token")

    result = await db.execute(
        select(AuthAssistantDevice).where(AuthAssistantDevice.token_hash == hash_secret(raw_token))
    )
    device = result.scalar_one_or_none()
    if device is None or device.status != AuthAssistantDeviceStatus.ACTIVE:
        raise HTTPException(status_code=401, detail="Invalid or revoked Auth Assistant device token")
    device.last_seen_at = utcnow_naive()
    return device


def _extract_device_token(authorization: str | None, x_auth_assistant_token: str | None) -> str | None:
    if x_auth_assistant_token and x_auth_assistant_token.strip():
        return x_auth_assistant_token.strip()
    if not authorization:
        return None
    scheme, _, value = authorization.strip().partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()
