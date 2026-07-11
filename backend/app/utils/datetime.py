"""Datetime helpers for consistent API serialization and business dates."""

from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.platform.config.settings import get_settings


@lru_cache(maxsize=16)
def _zoneinfo_for_name(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("Asia/Shanghai")


def user_timezone() -> ZoneInfo:
    """Return the configured business timezone for user-facing calendar dates."""
    configured = (get_settings().user_timezone or "Asia/Shanghai").strip() or "Asia/Shanghai"
    return _zoneinfo_for_name(configured)


def today_in_user_timezone() -> date:
    """Return today's business calendar date in ``USER_TIMEZONE``."""
    return datetime.now(user_timezone()).date()


def local_date_range_to_utc_naive(start_date: date, end_date: date) -> tuple[datetime, datetime]:
    """Convert an inclusive local business-date range to a UTC-naive DB window."""
    tz = user_timezone()
    start_local = datetime.combine(start_date, time.min, tzinfo=tz)
    end_local = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=tz)
    return (
        start_local.astimezone(timezone.utc).replace(tzinfo=None),
        end_local.astimezone(timezone.utc).replace(tzinfo=None),
    )


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
