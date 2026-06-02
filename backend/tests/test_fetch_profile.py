"""Tests for the rolling per-source fetch profile."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from app.domains.fetch.profile import record_fetch_result, summarize_profile


def _source(metadata=None):
    return SimpleNamespace(metadata_=dict(metadata or {}))


def test_records_success_and_summarizes():
    src = _source()
    now = datetime(2026, 6, 1, 12, 0, 0)
    record_fetch_result(src, outcome="success", saved_count=3, latency_ms=1000, now=now)
    record_fetch_result(src, outcome="success", saved_count=2, latency_ms=2000, now=now)
    summary = summarize_profile(src, now=now)
    assert summary["attempts_7d"] == 2
    assert summary["success_count_7d"] == 2
    assert summary["saved_count_7d"] == 5
    assert summary["success_rate_7d"] == 1.0
    assert summary["avg_latency_ms_7d"] == 1500


def test_mixed_outcomes_rate():
    src = _source()
    now = datetime(2026, 6, 1, 12, 0, 0)
    record_fetch_result(src, outcome="success", saved_count=1, now=now)
    record_fetch_result(src, outcome="failure", failure_code="http_429", now=now)
    record_fetch_result(src, outcome="empty", now=now)
    summary = summarize_profile(src, now=now)
    assert summary["attempts_7d"] == 3
    assert summary["success_count_7d"] == 1
    assert summary["failure_count_7d"] == 1
    assert summary["empty_count_7d"] == 1
    assert summary["success_rate_7d"] == round(1 / 3, 3)
    assert summary["last_failure_code"] == "http_429"


def test_fulltext_rate():
    src = _source()
    now = datetime(2026, 6, 1, 12, 0, 0)
    record_fetch_result(src, outcome="success", saved_count=4, fulltext_ok=3, fulltext_total=4, now=now)
    summary = summarize_profile(src, now=now)
    assert summary["fulltext_success_rate_7d"] == 0.75


def test_old_buckets_pruned_from_window():
    src = _source()
    old = datetime(2026, 5, 1, 12, 0, 0)
    now = datetime(2026, 6, 1, 12, 0, 0)
    record_fetch_result(src, outcome="success", saved_count=9, now=old)
    record_fetch_result(src, outcome="success", saved_count=1, now=now)
    summary = summarize_profile(src, now=now)
    # The 30-day-old bucket falls outside the 7d window.
    assert summary["attempts_7d"] == 1
    assert summary["saved_count_7d"] == 1


def test_preferred_strategy_recorded():
    src = _source()
    record_fetch_result(src, outcome="success", saved_count=1, preferred_strategy="rss")
    summary = summarize_profile(src)
    assert summary["preferred_strategy"] == "rss"


def test_empty_profile_summary_defaults():
    src = _source()
    summary = summarize_profile(src)
    assert summary["attempts_7d"] == 0
    assert summary["success_rate_7d"] is None
    assert summary["avg_latency_ms_7d"] is None
    assert summary["fulltext_success_rate_7d"] is None
