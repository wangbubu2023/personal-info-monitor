"""Datetime helpers for consistent API serialization."""

from datetime import datetime, timezone
from typing import Optional


def utcnow_naive() -> datetime:
    """Return current UTC time as naive datetime (legacy DB-compatible)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Treat naive datetime as UTC and return timezone-aware UTC datetime."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_iso_z(dt: Optional[datetime]) -> Optional[str]:
    """Serialize datetime to ISO-8601 with explicit UTC suffix Z."""
    aware = ensure_utc(dt)
    if aware is None:
        return None
    return aware.isoformat().replace("+00:00", "Z")
