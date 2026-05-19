"""Regression tests for Phase 2 Q1 bare-except refactors.

Covers the narrower `except ValueError:` paths that replaced the old
`except Exception: pass` samples in `app.pipeline.utils` and
`app.utils.publish_time`. If somebody re-broadens these handlers, the
dedicated tests below should fail fast.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.pipeline.utils import (
    _parse_iso_publish_time,
    normalize_publish_time,
    resolve_website_publish_time,
)
from app.utils.publish_time import parse_publish_time_text


class TestParseIsoPublishTime:
    def test_zulu_suffix_normalises_to_naive_utc(self):
        dt = _parse_iso_publish_time("2026-04-20T10:15:00Z")
        assert dt is not None
        assert dt.tzinfo is None
        assert dt.year == 2026 and dt.hour == 10

    def test_malformed_returns_none_without_swallowing_other_errors(self):
        assert _parse_iso_publish_time("not-a-date") is None

    def test_typeerror_still_propagates(self):
        """Only ValueError is tolerated — passing a non-string must blow up."""
        with pytest.raises(AttributeError):
            _parse_iso_publish_time(None)  # type: ignore[arg-type]


class TestNormalizePublishTime:
    @pytest.mark.asyncio
    async def test_iso_string_passthrough(self):
        raw = {"publish_time": "2026-04-20T10:15:00+00:00"}
        dt = await normalize_publish_time(raw, "rss")
        assert isinstance(dt, datetime)
        assert dt.year == 2026

    @pytest.mark.asyncio
    async def test_malformed_string_returns_none(self):
        raw = {"publish_time": "banana"}
        assert await normalize_publish_time(raw, "rss") is None

    @pytest.mark.asyncio
    async def test_existing_datetime_returned_verbatim(self):
        expected = datetime(2026, 1, 1, 12, 0, 0)
        raw = {"publish_time": expected}
        assert await normalize_publish_time(raw, "rss") == expected


class TestResolveWebsitePublishTime:
    @pytest.mark.asyncio
    async def test_estimated_triggers_url_fetch(self):
        """When metadata flags the publish_time as a guess we re-resolve it."""
        resolved = datetime(2026, 4, 1, 0, 0, 0)
        raw = {
            "url": "https://example.com/article",
            "metadata": {"publish_time_estimated": True},
        }

        with patch(
            "app.utils.publish_time.fetch_publish_time_from_url",
            new=AsyncMock(return_value=resolved),
        ):
            dt = await resolve_website_publish_time(raw)

        assert dt == resolved

    @pytest.mark.asyncio
    async def test_estimated_network_failure_returns_none(self):
        """The inner fetch helper owns its own error handling; we must not crash."""
        raw = {
            "url": "https://example.com/article",
            "metadata": {"publish_time_estimated": True},
        }

        with patch(
            "app.utils.publish_time.fetch_publish_time_from_url",
            new=AsyncMock(return_value=None),
        ):
            assert await resolve_website_publish_time(raw) is None


class TestParsePublishTimeText:
    def test_strptime_mismatch_keeps_trying_other_formats(self):
        """The tighter `except ValueError:` must still walk the format list.

        parse_publish_time_text assumes Asia/Shanghai wall-clock for date-only
        inputs and returns UTC-naive, so 2026/04/20 00:00 CN -> 2026/04/19 16:00 UTC.
        The important thing is that *some* parse happened (non-None).
        """
        dt = parse_publish_time_text("2026/04/20")
        assert dt is not None
        # Still within ±1 day of the expected calendar date.
        assert dt.year == 2026 and dt.month == 4 and dt.day in {19, 20}

    def test_completely_unknown_text_returns_none(self):
        assert parse_publish_time_text("publicly available yesterday") is None
