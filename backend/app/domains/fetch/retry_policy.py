"""Retry / cooldown / circuit-breaker bookkeeping for the fetch path.

This builds directly on :mod:`app.domains.fetch.failures`. The taxonomy answers
*"why did it fail?"*; this module answers *"what should the scheduler do about
it?"* by persisting the current circuit-breaker state onto structured
``sources.fetch_failure_*`` columns. For compatibility with older code and
isolated tests, the same state is still mirrored under
``Source.metadata_['fetch_failure']``::

    {
      "last_code": "http_429",
      "last_status": 429,
      "retryable": true,
      "severity": "warning",
      "cooldown_until": "2026-06-01T14:30:00Z",
      "consecutive_by_code": {"http_429": 3},
      "consecutive_failures": 3,
      "updated_at": "2026-06-01T14:15:00Z"
    }

The scheduler reads ``fetch_cooldown_until`` / ``cooldown_until`` to skip
automatic fetches without disabling the source outright, while manual triggers
bypass the cooldown entirely.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Mapping

from app.domains.fetch.failures import FetchFailure, FetchFailureCode, _POLICY
from app.utils.datetime import utcnow_naive

_FETCH_FAILURE_KEY = "fetch_failure"

# A hard ceiling so a long consecutive-failure streak can't push the cooldown
# arbitrarily far into the future.
_MAX_COOLDOWN_SECONDS = 6 * 3600


def cooldown_seconds_for_code(code: str) -> int | None:
    """Return the default cooldown (seconds) for a failure code string, if any."""
    try:
        enum_code = FetchFailureCode(code)
    except ValueError:
        return None
    _retryable, _severity, cooldown = _POLICY.get(enum_code, (True, "error", None))
    return cooldown


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    try:
        text = str(value).strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=None)


def _read_record(source) -> dict[str, Any]:
    structured = _read_structured_record(source)
    if structured:
        return structured
    raw = getattr(source, "metadata_", None)
    metadata = raw if isinstance(raw, Mapping) else {}
    record = metadata.get(_FETCH_FAILURE_KEY)
    if isinstance(record, Mapping):
        return dict(record)
    return {}


def _read_structured_record(source) -> dict[str, Any]:
    code = getattr(source, "fetch_failure_code", None)
    if not code:
        return {}
    consecutive = int(getattr(source, "fetch_failure_consecutive", None) or 0)
    cooldown_until = getattr(source, "fetch_cooldown_until", None)
    updated_at = getattr(source, "fetch_failure_updated_at", None)
    record: dict[str, Any] = {
        "last_code": code,
        "last_status": getattr(source, "fetch_failure_status", None),
        "severity": getattr(source, "fetch_failure_severity", None),
        "retryable": getattr(source, "fetch_failure_retryable", None),
        "consecutive_by_code": {str(code): consecutive} if consecutive else {},
        "consecutive_failures": consecutive,
    }
    if cooldown_until is not None:
        record["cooldown_until"] = cooldown_until.isoformat() + "Z"
    if updated_at is not None:
        record["updated_at"] = updated_at.isoformat() + "Z"
    return record


def _write_metadata(source, key: str, value: Any | None) -> None:
    metadata = dict(getattr(source, "metadata_", None) or {})
    if value is None:
        metadata.pop(key, None)
    else:
        metadata[key] = value
    source.metadata_ = metadata


def _write_structured_failure_state(
    source,
    *,
    code: str | None,
    http_status: int | None = None,
    severity: str | None = None,
    retryable: bool | None = None,
    consecutive_failures: int = 0,
    cooldown_until: datetime | None = None,
    updated_at: datetime | None = None,
) -> None:
    if not hasattr(source, "fetch_failure_code"):
        return
    source.fetch_failure_code = code
    source.fetch_failure_status = http_status
    source.fetch_failure_severity = severity
    source.fetch_failure_retryable = retryable
    source.fetch_failure_consecutive = int(consecutive_failures or 0)
    source.fetch_failure_updated_at = updated_at
    source.fetch_cooldown_until = cooldown_until


def record_fetch_failure(
    source,
    *,
    code: str,
    severity: str = "error",
    http_status: int | None = None,
    retryable: bool | None = None,
    cooldown_seconds: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Persist/refresh the circuit-breaker record after a failed fetch.

    Increments the per-code consecutive counter, recomputes ``cooldown_until``
    and returns the new record (also written back to ``source.metadata_``).
    """
    now = now or utcnow_naive()
    prev = _read_record(source)
    consecutive_by_code: dict[str, int] = dict(prev.get("consecutive_by_code") or {})
    consecutive_by_code[code] = int(consecutive_by_code.get(code, 0)) + 1
    consecutive_failures = int(prev.get("consecutive_failures", 0)) + 1

    if cooldown_seconds is None:
        cooldown_seconds = cooldown_seconds_for_code(code)

    record: dict[str, Any] = {
        "last_code": code,
        "last_status": http_status,
        "severity": severity,
        "retryable": bool(retryable) if retryable is not None else True,
        "consecutive_by_code": consecutive_by_code,
        "consecutive_failures": consecutive_failures,
        "updated_at": now.isoformat() + "Z",
    }

    if cooldown_seconds and cooldown_seconds > 0:
        # Escalate cooldown with the consecutive-failure streak for this code,
        # capped so it never runs away.
        streak = consecutive_by_code[code]
        scaled = min(cooldown_seconds * streak, _MAX_COOLDOWN_SECONDS)
        cooldown_until = now + timedelta(seconds=scaled)
        record["cooldown_until"] = cooldown_until.isoformat() + "Z"
        record["cooldown_seconds"] = scaled
    else:
        cooldown_until = None

    _write_structured_failure_state(
        source,
        code=code,
        http_status=http_status,
        severity=severity,
        retryable=record["retryable"],
        consecutive_failures=consecutive_failures,
        cooldown_until=cooldown_until,
        updated_at=now,
    )
    _write_metadata(source, _FETCH_FAILURE_KEY, record)
    return record


def record_fetch_failure_from(source, failure: FetchFailure, *, now: datetime | None = None) -> dict[str, Any]:
    """Convenience wrapper that records from a :class:`FetchFailure`."""
    return record_fetch_failure(
        source,
        code=failure.code.value,
        severity=failure.severity,
        http_status=failure.http_status,
        retryable=failure.retryable,
        cooldown_seconds=failure.cooldown_seconds,
        now=now,
    )


def clear_fetch_failure(source) -> None:
    """Reset the circuit-breaker record after a successful fetch."""
    _write_structured_failure_state(source, code=None)
    if _read_record(source):
        _write_metadata(source, _FETCH_FAILURE_KEY, None)


def get_cooldown_until(source) -> datetime | None:
    """Return the active cooldown deadline, or ``None`` when not cooling down."""
    structured_deadline = getattr(source, "fetch_cooldown_until", None)
    if isinstance(structured_deadline, datetime):
        return structured_deadline.replace(tzinfo=None)
    record = _read_record(source)
    return _parse_dt(record.get("cooldown_until"))


def is_in_cooldown(source, *, now: datetime | None = None) -> bool:
    """Whether the source is currently within an active fetch cooldown window."""
    deadline = get_cooldown_until(source)
    if deadline is None:
        return False
    return (now or utcnow_naive()) < deadline


__all__ = [
    "cooldown_seconds_for_code",
    "record_fetch_failure",
    "record_fetch_failure_from",
    "clear_fetch_failure",
    "get_cooldown_until",
    "is_in_cooldown",
]
