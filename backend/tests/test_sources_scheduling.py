"""Tests for the canonical scheduling rules in ``app.domains.sources.scheduling``.

Phase 1 of the refactor lifted ``_effective_due_interval_minutes`` out of
``app.tasks.fetch_tasks`` so the scheduler, the HTTP status read model
and the ``MonitorService`` could share a single implementation. These
tests pin down the behaviour at the new home.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.domains.sources.scheduling import (
    effective_due_interval_minutes,
    get_due_sources,
    is_due,
    list_due_source_ids,
    next_fetch_at_for,
)
from app.models.source import SourceType


def _make_source(**overrides):
    """Build a minimal in-memory stand-in for the ORM ``Source`` row."""
    defaults = {
        "id": "src-1",
        "fetch_interval": 30,
        "error_count": 0,
        "last_fetched_at": datetime(2026, 5, 1, 12, 0, 0),
        "enabled": True,
        "type": SourceType.RSS,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestEffectiveDueIntervalMinutes:
    def test_baseline_is_within_jitter_window(self):
        source = _make_source(fetch_interval=60, error_count=0)
        minutes = effective_due_interval_minutes(source)
        # ±10% jitter band around the configured 60-minute base
        assert 54.0 <= minutes <= 66.0

    def test_exponential_backoff_doubles_per_error(self):
        baseline = effective_due_interval_minutes(_make_source(fetch_interval=10, error_count=0))
        with_one_error = effective_due_interval_minutes(_make_source(fetch_interval=10, error_count=1))
        with_two_errors = effective_due_interval_minutes(_make_source(fetch_interval=10, error_count=2))
        # The jitter window guarantees doubling cannot collapse the ratio
        assert with_one_error >= baseline * 1.5
        assert with_two_errors >= with_one_error * 1.5

    def test_backoff_caps_at_32x_after_five_errors(self):
        capped = effective_due_interval_minutes(_make_source(fetch_interval=1, error_count=5))
        deeper = effective_due_interval_minutes(_make_source(fetch_interval=1, error_count=10))
        # Both error counts ≥ 5 should share the same 2**5 = 32× cap
        assert abs(capped - deeper) <= capped * 0.05

    def test_jitter_is_deterministic_for_fixed_cycle(self):
        s = _make_source()
        first = effective_due_interval_minutes(s)
        second = effective_due_interval_minutes(s)
        assert first == pytest.approx(second)

    def test_fetch_interval_defaults_to_60_when_falsy(self):
        source = _make_source(fetch_interval=0)
        minutes = effective_due_interval_minutes(source)
        assert 54.0 <= minutes <= 66.0


class TestNextFetchAtFor:
    def test_returns_none_when_never_fetched(self):
        source = _make_source(last_fetched_at=None)
        assert next_fetch_at_for(source) is None

    def test_returns_last_fetched_plus_interval(self):
        last = datetime(2026, 5, 1, 12, 0, 0)
        source = _make_source(last_fetched_at=last, fetch_interval=60, error_count=0)
        expected_min = last + timedelta(minutes=54)
        expected_max = last + timedelta(minutes=66)
        actual = next_fetch_at_for(source)
        assert expected_min <= actual <= expected_max


class TestIsDue:
    def test_never_fetched_is_always_due(self):
        assert is_due(_make_source(last_fetched_at=None)) is True

    def test_due_when_now_exceeds_next_fetch(self):
        source = _make_source(
            fetch_interval=10,
            error_count=0,
            last_fetched_at=datetime(2026, 5, 1, 12, 0, 0),
        )
        # Far in the future — must be due regardless of jitter
        assert is_due(source, now=datetime(2026, 5, 1, 14, 0, 0)) is True

    def test_not_due_when_within_interval(self):
        source = _make_source(
            fetch_interval=60,
            error_count=0,
            last_fetched_at=datetime(2026, 5, 1, 12, 0, 0),
        )
        # 30 minutes after last fetch — half the base interval
        assert is_due(source, now=datetime(2026, 5, 1, 12, 30, 0)) is False


class TestListDueSourceIds:
    def _fake_db(self, sources):
        """Build a minimal ``db.query(...).filter(...).filter(...).all()`` chain."""
        query = MagicMock()
        query.filter.return_value = query
        query.all.return_value = sources
        db = MagicMock()
        db.query.return_value = query
        return db

    def test_returns_due_source_ids_only(self):
        due = _make_source(id="due", last_fetched_at=None)
        not_due = _make_source(
            id="fresh",
            fetch_interval=120,
            last_fetched_at=datetime(2026, 5, 1, 12, 0, 0),
        )
        db = self._fake_db([due, not_due])
        result = list_due_source_ids(db, now=datetime(2026, 5, 1, 12, 30, 0))
        assert result == ["due"]

    def test_excludes_podcast_when_feature_disabled(self):
        """include_podcast=False adds a Source.type filter on top of enabled.is_(True)."""
        db = self._fake_db([])
        list_due_source_ids(db, include_podcast=False)
        # The outer ``query`` MagicMock was reused so .filter was called
        # twice: once for ``enabled`` and once for ``type != PODCAST``.
        outer_query = db.query.return_value
        assert outer_query.filter.call_count == 2


class TestGetDueSources:
    def test_returns_orm_rows(self):
        due = _make_source(id="due", last_fetched_at=None)
        not_due = _make_source(
            id="fresh",
            fetch_interval=120,
            last_fetched_at=datetime(2026, 5, 1, 12, 0, 0),
        )
        query = MagicMock()
        query.filter.return_value = query
        query.all.return_value = [due, not_due]
        db = MagicMock()
        db.query.return_value = query
        result = get_due_sources(db, now=datetime(2026, 5, 1, 12, 30, 0))
        assert [s.id for s in result] == ["due"]


class TestCanonicalImportPath:
    def test_canonical_function_is_importable_from_domain(self):
        """Phase 7 retired the ``app.tasks.fetch_tasks._effective_due_interval_minutes``
        alias; callers must import :func:`effective_due_interval_minutes`
        from :mod:`app.domains.sources.scheduling` directly.
        """
        from app.domains.sources.scheduling import effective_due_interval_minutes as canonical

        assert canonical is effective_due_interval_minutes
