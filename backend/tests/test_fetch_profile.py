"""Tests for the rolling per-source fetch profile."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.domains.fetch.profile import record_fetch_result, summarize_profile
from app.models import Source, SourceFetchLog
from app.models.source import SourceType


def _source(metadata=None):
    return SimpleNamespace(metadata_=dict(metadata or {}))


def _db_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'fetch_profile.db'}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


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


def test_fetch_profile_persists_attempt_log_and_summarizes_from_table(tmp_path):
    db = _db_session(tmp_path)
    try:
        source = Source(name="Logged Source", type=SourceType.RSS, url="https://example.com/feed")
        db.add(source)
        db.flush()
        now = datetime(2026, 6, 1, 12, 0, 0)

        record_fetch_result(
            source,
            outcome="success",
            saved_count=3,
            latency_ms=1200,
            fulltext_ok=2,
            fulltext_total=3,
            preferred_strategy="rss",
            severity="info",
            now=now,
        )
        record_fetch_result(
            source,
            outcome="failure",
            failure_code="http_429",
            latency_ms=800,
            severity="warning",
            now=now + timedelta(minutes=5),
        )

        rows = db.query(SourceFetchLog).filter(SourceFetchLog.source_id == source.id).all()
        assert len(rows) == 2
        assert rows[0].preferred_strategy == "rss"
        assert rows[1].failure_code == "http_429"
        assert rows[1].severity == "warning"

        # The table is authoritative when present, even if legacy metadata is stale.
        source.metadata_ = {"fetch_profile": {"buckets": {}}}
        summary = summarize_profile(source, now=now + timedelta(minutes=10))

        assert summary["attempts_7d"] == 2
        assert summary["success_count_7d"] == 1
        assert summary["failure_count_7d"] == 1
        assert summary["saved_count_7d"] == 3
        assert summary["avg_latency_ms_7d"] == 1000
        assert summary["fulltext_success_rate_7d"] == round(2 / 3, 3)
        assert summary["last_failure_code"] == "http_429"
        assert summary["preferred_strategy"] == "rss"
    finally:
        bind = db.get_bind()
        db.close()
        bind.dispose()
