"""Tests for fetch retry/cooldown circuit-breaker bookkeeping."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from app.domains.fetch.failures import make_failure, FetchFailureCode
from app.domains.fetch.retry_policy import (
    clear_fetch_failure,
    cooldown_seconds_for_code,
    get_cooldown_until,
    is_in_cooldown,
    record_fetch_failure,
    record_fetch_failure_from,
)
from app.interfaces.http.sources._helpers import _fetch_health_fields
from app.models.source import Source, SourceType


def _source(metadata=None):
    return SimpleNamespace(metadata_=dict(metadata or {}))


def _orm_source(metadata=None):
    return Source(name="Example", type=SourceType.RSS, url="https://example.com/feed", metadata_=dict(metadata or {}))


def test_cooldown_seconds_for_code():
    assert cooldown_seconds_for_code("http_429") == 900
    assert cooldown_seconds_for_code("http_403") == 3600
    assert cooldown_seconds_for_code("http_5xx") == 120
    assert cooldown_seconds_for_code("timeout") is None
    assert cooldown_seconds_for_code("not_a_code") is None


def test_record_failure_sets_cooldown_and_counters():
    src = _source()
    now = datetime(2026, 6, 1, 12, 0, 0)
    record = record_fetch_failure(src, code="http_429", severity="warning", http_status=429, retryable=True, now=now)
    assert record["last_code"] == "http_429"
    assert record["consecutive_by_code"]["http_429"] == 1
    assert record["consecutive_failures"] == 1
    cooldown = get_cooldown_until(src)
    assert cooldown == now + timedelta(seconds=900)


def test_cooldown_escalates_with_streak_and_caps():
    src = _source()
    now = datetime(2026, 6, 1, 12, 0, 0)
    record_fetch_failure(src, code="http_429", now=now)
    record_fetch_failure(src, code="http_429", now=now)
    rec = record_fetch_failure(src, code="http_429", now=now)
    assert rec["consecutive_by_code"]["http_429"] == 3
    # 900 * 3 = 2700s
    assert get_cooldown_until(src) == now + timedelta(seconds=2700)


def test_cooldown_is_capped():
    src = _source()
    now = datetime(2026, 6, 1, 12, 0, 0)
    for _ in range(100):
        record_fetch_failure(src, code="http_403", now=now)  # 3600s each
    # Capped at 6h.
    assert get_cooldown_until(src) == now + timedelta(seconds=6 * 3600)


def test_timeout_failure_has_no_cooldown():
    src = _source()
    record_fetch_failure(src, code="timeout")
    assert get_cooldown_until(src) is None
    assert is_in_cooldown(src) is False


def test_is_in_cooldown_window():
    src = _source()
    now = datetime(2026, 6, 1, 12, 0, 0)
    record_fetch_failure(src, code="http_429", now=now)
    assert is_in_cooldown(src, now=now + timedelta(seconds=10)) is True
    assert is_in_cooldown(src, now=now + timedelta(seconds=1000)) is False


def test_clear_failure_resets():
    src = _source()
    record_fetch_failure(src, code="http_429")
    assert "fetch_failure" in src.metadata_
    clear_fetch_failure(src)
    assert "fetch_failure" not in src.metadata_
    assert is_in_cooldown(src) is False


def test_record_from_failure_object():
    src = _source()
    failure = make_failure(FetchFailureCode.HTTP_429, http_status=429, cooldown_seconds=120)
    now = datetime(2026, 6, 1, 12, 0, 0)
    record_fetch_failure_from(src, failure, now=now)
    assert get_cooldown_until(src) == now + timedelta(seconds=120)


def test_record_preserves_other_metadata():
    src = _source({"rss_url": "https://x/feed"})
    record_fetch_failure(src, code="http_429")
    assert src.metadata_["rss_url"] == "https://x/feed"


def test_record_failure_mirrors_structured_source_columns():
    src = _orm_source()
    now = datetime(2026, 6, 1, 12, 0, 0)

    record = record_fetch_failure(
        src,
        code="http_429",
        severity="warning",
        http_status=429,
        retryable=True,
        now=now,
    )

    cooldown_until = now + timedelta(seconds=900)
    assert record["cooldown_until"] == cooldown_until.isoformat() + "Z"
    assert src.fetch_failure_code == "http_429"
    assert src.fetch_failure_status == 429
    assert src.fetch_failure_severity == "warning"
    assert src.fetch_failure_retryable is True
    assert src.fetch_failure_consecutive == 1
    assert src.fetch_failure_updated_at == now
    assert src.fetch_cooldown_until == cooldown_until
    assert get_cooldown_until(src) == cooldown_until

    clear_fetch_failure(src)

    assert src.fetch_failure_code is None
    assert src.fetch_failure_status is None
    assert src.fetch_failure_severity is None
    assert src.fetch_failure_retryable is None
    assert src.fetch_failure_consecutive == 0
    assert src.fetch_failure_updated_at is None
    assert src.fetch_cooldown_until is None
    assert "fetch_failure" not in src.metadata_


def test_structured_failure_state_is_authoritative_over_stale_metadata():
    structured_deadline = datetime(2026, 6, 1, 13, 0, 0)
    stale_deadline = datetime(2026, 6, 1, 15, 0, 0)
    src = _orm_source(
        {
            "fetch_failure": {
                "last_code": "http_403",
                "cooldown_until": stale_deadline.isoformat() + "Z",
            }
        }
    )
    src.fetch_failure_code = "http_429"
    src.fetch_failure_status = 429
    src.fetch_failure_severity = "warning"
    src.fetch_failure_retryable = True
    src.fetch_failure_consecutive = 2
    src.fetch_failure_updated_at = datetime(2026, 6, 1, 12, 30, 0)
    src.fetch_cooldown_until = structured_deadline

    assert get_cooldown_until(src) == structured_deadline
    assert is_in_cooldown(src, now=datetime(2026, 6, 1, 12, 45, 0)) is True

    fields = _fetch_health_fields(src, src.metadata_)
    assert fields["last_failure_code"] == "http_429"
    assert fields["cooldown_until"] == structured_deadline.isoformat() + "Z"
