"""Tests for humanized timing helpers.

These helpers are anti-bot insurance: we verify bounds and core invariants
(centered around base, minimum floor, scroll walks the full page) using a
seeded RNG so any regression shows up as a deterministic failure instead of
a flaky one.
"""

from __future__ import annotations

import random
from unittest.mock import AsyncMock, MagicMock

import pytest

from datetime import datetime, timedelta

from app.utils.human_timing import (
    human_inter_request_pause,
    human_scroll_page,
    humanized_wait_ms,
    jittered_interval_minutes,
)


class TestHumanizedWaitMs:
    def test_zero_base_respects_floor(self):
        assert humanized_wait_ms(0) == 0
        assert humanized_wait_ms(0, floor_ms=500) == 500

    def test_distribution_centered_within_band(self):
        random.seed(12345)
        samples = [humanized_wait_ms(1000, jitter_pct=0.3) for _ in range(500)]
        assert all(700 <= s <= 1300 for s in samples)
        # With 500 samples, the mean should sit close to the base; a wide
        # 5% band keeps the test non-flaky while still catching "always
        # returns base".
        mean = sum(samples) / len(samples)
        assert 950 <= mean <= 1050
        assert len(set(samples)) > 20  # not a constant

    def test_floor_clamps_low_end(self):
        random.seed(42)
        samples = [humanized_wait_ms(1000, jitter_pct=0.5, floor_ms=800) for _ in range(200)]
        assert min(samples) >= 800
        # Upper end unaffected
        assert max(samples) <= 1500

    def test_negative_or_nonsense_jitter_is_safe(self):
        # Negative jitter gets clamped; function must not crash.
        assert humanized_wait_ms(1000, jitter_pct=-0.3) == 1000

    def test_small_base_with_floor(self):
        """Base below the floor should promote to the floor, not collapse."""
        assert humanized_wait_ms(200, jitter_pct=0.5, floor_ms=500) >= 500


class TestHumanInterRequestPause:
    @pytest.mark.asyncio
    async def test_sleep_within_bounds(self, monkeypatch):
        slept: list[float] = []

        async def fake_sleep(duration: float) -> None:
            slept.append(duration)

        monkeypatch.setattr("app.utils.human_timing.asyncio.sleep", fake_sleep)

        random.seed(99)
        for _ in range(100):
            await human_inter_request_pause(min_ms=500, max_ms=1500)

        assert slept, "sleep must be invoked"
        assert all(0.5 <= d <= 1.5 for d in slept)
        # Values vary
        assert len({round(d, 3) for d in slept}) > 10

    @pytest.mark.asyncio
    async def test_zero_range_is_noop(self, monkeypatch):
        calls: list[float] = []
        monkeypatch.setattr(
            "app.utils.human_timing.asyncio.sleep",
            lambda d: calls.append(d) or AsyncMock()(),
        )
        await human_inter_request_pause(min_ms=0, max_ms=0)
        assert not calls

    @pytest.mark.asyncio
    async def test_inverted_bounds_coerced(self, monkeypatch):
        slept: list[float] = []

        async def fake_sleep(duration: float) -> None:
            slept.append(duration)

        monkeypatch.setattr("app.utils.human_timing.asyncio.sleep", fake_sleep)
        await human_inter_request_pause(min_ms=2000, max_ms=500)
        # min > max should not raise; function falls back to min.
        assert slept == [2.0]


class TestHumanScrollPage:
    @pytest.mark.asyncio
    async def test_walks_page_in_multiple_steps(self):
        page = MagicMock()
        page.evaluate = AsyncMock(return_value=3000)
        page.wait_for_timeout = AsyncMock()

        random.seed(7)
        await human_scroll_page(page, steps=3)

        # One evaluate() call for height, plus at least 2 scroll evaluate()
        # calls — verifies we didn't collapse into a single jump.
        scroll_calls = [c for c in page.evaluate.await_args_list if len(c.args) >= 2]
        assert len(scroll_calls) >= 2
        # Pauses between scroll steps.
        assert page.wait_for_timeout.await_count >= 2

    @pytest.mark.asyncio
    async def test_noop_when_height_unknown(self):
        page = MagicMock()
        page.evaluate = AsyncMock(return_value=None)
        page.wait_for_timeout = AsyncMock()

        await human_scroll_page(page)

        # Only the height probe, no scroll evaluate calls or waits.
        assert page.evaluate.await_count == 1
        page.wait_for_timeout.assert_not_called()

    @pytest.mark.asyncio
    async def test_survives_evaluate_errors(self):
        page = MagicMock()
        page.evaluate = AsyncMock(side_effect=RuntimeError("evaluate blew up"))
        page.wait_for_timeout = AsyncMock()

        # Should not raise; scrolling is best-effort.
        await human_scroll_page(page)
        page.wait_for_timeout.assert_not_called()


class TestJitteredIntervalMinutes:
    """The jittered-interval helper underpins both the SQL-free due check and
    the status API's displayed ``next_fetch_at``. Determinism within a cycle
    is the critical invariant: any non-determinism would let the scheduler
    and the API disagree on whether a source is overdue."""

    def test_returns_base_when_never_fetched(self):
        # Without an anchor there's nothing to hash, so jitter is meaningless
        # and the function returns the base interval untouched.
        assert jittered_interval_minutes("src-abc", 60, None) == 60

    def test_non_positive_base_passes_through(self):
        assert jittered_interval_minutes("src-abc", 0, datetime(2026, 4, 22)) == 0
        assert jittered_interval_minutes("src-abc", -5, datetime(2026, 4, 22)) == -5

    def test_result_stays_within_jitter_band(self):
        anchor = datetime(2026, 4, 22, 12, 0, 0)
        values = [
            jittered_interval_minutes(f"src-{i}", 60, anchor, jitter_pct=0.1)
            for i in range(200)
        ]
        assert all(54.0 <= v <= 66.0 for v in values)

    def test_deterministic_per_source_cycle(self):
        # Same (source_id, last_fetched_at) must yield same value so the
        # scheduler and status API agree — flaky jitter here would cause
        # phantom "overdue" states.
        anchor = datetime(2026, 4, 22, 12, 0, 0)
        a = jittered_interval_minutes("src-abc", 60, anchor)
        b = jittered_interval_minutes("src-abc", 60, anchor)
        assert a == b

    def test_rerolls_after_new_fetch(self):
        t1 = datetime(2026, 4, 22, 12, 0, 0)
        t2 = t1 + timedelta(hours=1)
        a = jittered_interval_minutes("src-abc", 60, t1)
        b = jittered_interval_minutes("src-abc", 60, t2)
        # Reasonable P(same jitter) ≈ 0; any equality here signals a hash bug.
        assert a != b

    def test_different_sources_decorrelate(self):
        anchor = datetime(2026, 4, 22, 12, 0, 0)
        values = {
            jittered_interval_minutes(f"src-{i:04d}", 60, anchor)
            for i in range(50)
        }
        # Far more than 1 distinct value — sources must not all converge.
        assert len(values) >= 45

    def test_zero_jitter_pct_preserves_base(self):
        anchor = datetime(2026, 4, 22, 12, 0, 0)
        assert jittered_interval_minutes("src-abc", 60, anchor, jitter_pct=0.0) == 60
