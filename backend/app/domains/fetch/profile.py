"""Per-source fetch profile (rolling 7-day health picture).

A long-term complement to the per-attempt :mod:`failures` taxonomy and the
:mod:`retry_policy` circuit breaker. Each fetch records a lightweight outcome
into ``source_fetch_log`` when the source is attached to a SQLAlchemy session;
the legacy ``Source.metadata_['fetch_profile']`` buckets are still written as a
compatibility fallback for old rows and isolated unit tests.

Stored shape::

    {
      "buckets": {
        "2026-06-01": {"success": 4, "failure": 1, "empty": 2, "saved": 9,
                        "latency_ms_sum": 8200, "latency_n": 5,
                        "fulltext_ok": 7, "fulltext_n": 9},
        ...
      },
      "last_success_at": "...Z",
      "last_failure_at": "...Z",
      "last_failure_code": "http_429",
      "preferred_strategy": "rss",
      "updated_at": "...Z"
    }

``summarize_profile`` produces the flattened ``*_7d`` fields the status API /
UI consume. It reads the log table first and falls back to metadata buckets
when no table rows exist.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal, Mapping

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm.exc import UnmappedInstanceError
from sqlalchemy.orm import object_session

from app.models.source_fetch_log import SourceFetchLog
from app.utils.datetime import utcnow_naive

_PROFILE_KEY = "fetch_profile"
_WINDOW_DAYS = 7

Outcome = Literal["success", "failure", "empty"]


def _day_key(dt: datetime) -> str:
    return dt.date().isoformat()


def _read_profile(source) -> dict[str, Any]:
    raw = getattr(source, "metadata_", None)
    metadata = raw if isinstance(raw, Mapping) else {}
    profile = metadata.get(_PROFILE_KEY)
    return dict(profile) if isinstance(profile, Mapping) else {}


def _write_profile(source, profile: dict[str, Any]) -> None:
    metadata = dict(getattr(source, "metadata_", None) or {})
    metadata[_PROFILE_KEY] = profile
    source.metadata_ = metadata


def _source_session_and_id(source) -> tuple[Any | None, str | None]:
    source_id = getattr(source, "id", None)
    if source_id is None:
        return None, None
    try:
        db = object_session(source)
    except UnmappedInstanceError:
        db = None
    return db, str(source_id)


def _prune_buckets(buckets: dict[str, Any], *, now: datetime) -> dict[str, dict[str, Any]]:
    cutoff = (now - timedelta(days=_WINDOW_DAYS)).date()
    pruned: dict[str, dict[str, Any]] = {}
    for key, value in buckets.items():
        if not isinstance(value, Mapping):
            continue
        try:
            day = datetime.fromisoformat(str(key)).date()
        except (TypeError, ValueError):
            continue
        if day >= cutoff:
            pruned[key] = dict(value)
    return pruned


def record_fetch_result(
    source,
    *,
    outcome: Outcome,
    saved_count: int = 0,
    latency_ms: float | None = None,
    fulltext_ok: int | None = None,
    fulltext_total: int | None = None,
    failure_code: str | None = None,
    preferred_strategy: str | None = None,
    severity: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Fold a single fetch outcome into the rolling profile and return it."""
    now = now or utcnow_naive()
    profile = _read_profile(source)
    buckets = _prune_buckets(profile.get("buckets") or {}, now=now)

    key = _day_key(now)
    bucket = dict(buckets.get(key) or {})
    for field in ("success", "failure", "empty", "saved", "latency_ms_sum", "latency_n", "fulltext_ok", "fulltext_n"):
        bucket.setdefault(field, 0)

    if outcome in ("success", "failure", "empty"):
        bucket[outcome] += 1
    bucket["saved"] += max(0, int(saved_count or 0))
    if latency_ms is not None and latency_ms >= 0:
        bucket["latency_ms_sum"] += int(latency_ms)
        bucket["latency_n"] += 1
    if fulltext_total:
        bucket["fulltext_ok"] += max(0, int(fulltext_ok or 0))
        bucket["fulltext_n"] += int(fulltext_total)

    buckets[key] = bucket
    profile["buckets"] = buckets
    profile["updated_at"] = now.isoformat() + "Z"
    if outcome == "success":
        profile["last_success_at"] = now.isoformat() + "Z"
    elif outcome == "failure":
        profile["last_failure_at"] = now.isoformat() + "Z"
        if failure_code:
            profile["last_failure_code"] = failure_code
    if preferred_strategy:
        profile["preferred_strategy"] = preferred_strategy

    db, source_id = _source_session_and_id(source)
    if db is not None and source_id:
        db.add(
            SourceFetchLog(
                source_id=source_id,
                attempted_at=now,
                outcome=outcome,
                severity=severity[:16] if severity else None,
                failure_code=failure_code if outcome == "failure" else None,
                saved_count=max(0, int(saved_count or 0)),
                latency_ms=int(latency_ms) if latency_ms is not None and latency_ms >= 0 else None,
                fulltext_ok=max(0, int(fulltext_ok or 0)),
                fulltext_total=max(0, int(fulltext_total or 0)),
                preferred_strategy=preferred_strategy[:64] if preferred_strategy else None,
            )
        )

    _write_profile(source, profile)
    return profile


def _empty_summary() -> dict[str, Any]:
    return {
        "attempts_7d": 0,
        "success_count_7d": 0,
        "failure_count_7d": 0,
        "empty_count_7d": 0,
        "saved_count_7d": 0,
        "success_rate_7d": None,
        "avg_latency_ms_7d": None,
        "fulltext_success_rate_7d": None,
        "last_success_at": None,
        "last_failure_at": None,
        "last_failure_code": None,
        "preferred_strategy": None,
    }


def _summarize_logs(source, *, now: datetime) -> dict[str, Any] | None:
    db, source_id = _source_session_and_id(source)
    if db is None or not source_id:
        return None
    cutoff = now - timedelta(days=_WINDOW_DAYS)
    try:
        rows = (
            db.query(SourceFetchLog)
            .filter(SourceFetchLog.source_id == source_id)
            .filter(SourceFetchLog.attempted_at >= cutoff)
            .order_by(SourceFetchLog.attempted_at.asc())
            .all()
        )
    except SQLAlchemyError:
        return None
    if not rows:
        return None

    success = sum(1 for row in rows if row.outcome == "success")
    failure = sum(1 for row in rows if row.outcome == "failure")
    empty = sum(1 for row in rows if row.outcome == "empty")
    saved = sum(max(0, int(row.saved_count or 0)) for row in rows)
    latency_values = [int(row.latency_ms) for row in rows if row.latency_ms is not None and row.latency_ms >= 0]
    fulltext_ok = sum(max(0, int(row.fulltext_ok or 0)) for row in rows)
    fulltext_n = sum(max(0, int(row.fulltext_total or 0)) for row in rows)
    attempts = success + failure + empty
    last_success = next((row for row in reversed(rows) if row.outcome == "success"), None)
    last_failure = next((row for row in reversed(rows) if row.outcome == "failure"), None)
    preferred = next((row.preferred_strategy for row in reversed(rows) if row.preferred_strategy), None)
    return {
        "attempts_7d": attempts,
        "success_count_7d": success,
        "failure_count_7d": failure,
        "empty_count_7d": empty,
        "saved_count_7d": saved,
        "success_rate_7d": round(success / attempts, 3) if attempts else None,
        "avg_latency_ms_7d": round(sum(latency_values) / len(latency_values)) if latency_values else None,
        "fulltext_success_rate_7d": round(fulltext_ok / fulltext_n, 3) if fulltext_n else None,
        "last_success_at": last_success.attempted_at.isoformat() + "Z" if last_success else None,
        "last_failure_at": last_failure.attempted_at.isoformat() + "Z" if last_failure else None,
        "last_failure_code": last_failure.failure_code if last_failure else None,
        "preferred_strategy": preferred,
    }


def summarize_profile(source, *, now: datetime | None = None) -> dict[str, Any]:
    """Flatten the stored profile into the ``*_7d`` aggregate shape for the API."""
    now = now or utcnow_naive()
    from_logs = _summarize_logs(source, now=now)
    if from_logs is not None:
        return from_logs

    profile = _read_profile(source)
    buckets = _prune_buckets(profile.get("buckets") or {}, now=now)

    success = failure = empty = saved = 0
    latency_sum = latency_n = 0
    fulltext_ok = fulltext_n = 0
    for bucket in buckets.values():
        success += int(bucket.get("success", 0))
        failure += int(bucket.get("failure", 0))
        empty += int(bucket.get("empty", 0))
        saved += int(bucket.get("saved", 0))
        latency_sum += int(bucket.get("latency_ms_sum", 0))
        latency_n += int(bucket.get("latency_n", 0))
        fulltext_ok += int(bucket.get("fulltext_ok", 0))
        fulltext_n += int(bucket.get("fulltext_n", 0))

    attempts = success + failure + empty
    summary = _empty_summary()
    summary.update(
        {
            "attempts_7d": attempts,
            "success_count_7d": success,
            "failure_count_7d": failure,
            "empty_count_7d": empty,
            "saved_count_7d": saved,
            "success_rate_7d": round(success / attempts, 3) if attempts else None,
            "avg_latency_ms_7d": round(latency_sum / latency_n) if latency_n else None,
            "fulltext_success_rate_7d": round(fulltext_ok / fulltext_n, 3) if fulltext_n else None,
            "last_success_at": profile.get("last_success_at"),
            "last_failure_at": profile.get("last_failure_at"),
            "last_failure_code": profile.get("last_failure_code"),
            "preferred_strategy": profile.get("preferred_strategy"),
        }
    )
    return summary


__all__ = [
    "record_fetch_result",
    "summarize_profile",
]
