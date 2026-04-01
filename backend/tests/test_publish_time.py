"""Tests for app.utils.publish_time — date parsing and extraction."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.utils.publish_time import (
    _to_utc_naive,
    parse_publish_time_text,
    _extract_meta_publish_time,
    _extract_jsonld_publish_time,
    _extract_time_tag_publish_time,
    _extract_labeled_publish_time,
    extract_publish_time_from_html,
    fetch_publish_time_from_url,
)


# ---------------------------------------------------------------------------
# _to_utc_naive
# ---------------------------------------------------------------------------

class TestToUtcNaive:

    def test_utc_aware_to_naive(self):
        dt = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        result = _to_utc_naive(dt)
        assert result == datetime(2025, 6, 15, 12, 0, 0)
        assert result.tzinfo is None

    def test_naive_default_assumes_utc(self):
        dt = datetime(2025, 6, 15, 12, 0, 0)
        result = _to_utc_naive(dt, assume_cn_tz=False)
        assert result == datetime(2025, 6, 15, 12, 0, 0)

    def test_naive_assumes_cn_tz(self):
        dt = datetime(2025, 6, 15, 16, 0, 0)
        result = _to_utc_naive(dt, assume_cn_tz=True)
        assert result == datetime(2025, 6, 15, 8, 0, 0)

    def test_non_utc_timezone_converts(self):
        eastern = timezone(timedelta(hours=-5))
        dt = datetime(2025, 6, 15, 12, 0, 0, tzinfo=eastern)
        result = _to_utc_naive(dt)
        assert result == datetime(2025, 6, 15, 17, 0, 0)


# ---------------------------------------------------------------------------
# parse_publish_time_text
# ---------------------------------------------------------------------------

class TestParsePublishTimeText:

    def test_empty_returns_none(self):
        assert parse_publish_time_text("") is None
        assert parse_publish_time_text(None) is None

    def test_relative_minutes(self):
        with patch("app.utils.publish_time.utcnow_naive", return_value=datetime(2025, 6, 15, 12, 0, 0)):
            result = parse_publish_time_text("30分钟前")
        assert result == datetime(2025, 6, 15, 11, 30, 0)

    def test_relative_hours(self):
        with patch("app.utils.publish_time.utcnow_naive", return_value=datetime(2025, 6, 15, 12, 0, 0)):
            result = parse_publish_time_text("2小时前")
        assert result == datetime(2025, 6, 15, 10, 0, 0)

    def test_relative_days(self):
        with patch("app.utils.publish_time.utcnow_naive", return_value=datetime(2025, 6, 15, 12, 0, 0)):
            result = parse_publish_time_text("3天前")
        assert result == datetime(2025, 6, 12, 12, 0, 0)

    def test_absolute_chinese_datetime(self):
        result = parse_publish_time_text("2026年02月10日 17:02")
        assert result is not None
        assert result.year == 2026
        assert result.month == 2
        assert result.day == 10

    def test_absolute_chinese_date_only(self):
        result = parse_publish_time_text("2026年03月15日")
        assert result is not None
        assert result.year == 2026
        assert result.month == 3

    def test_iso_format_dash(self):
        result = parse_publish_time_text("2025-06-15 10:30:00")
        assert result is not None
        assert result.year == 2025
        assert result.month == 6
        assert result.day == 15

    def test_iso_format_slash(self):
        result = parse_publish_time_text("2025/06/15 10:30")
        assert result is not None
        assert result.year == 2025

    def test_date_only_dash(self):
        result = parse_publish_time_text("2025-06-15")
        assert result is not None
        assert result.year == 2025

    def test_date_only_slash(self):
        result = parse_publish_time_text("2025/06/15")
        assert result is not None

    def test_english_month_format(self):
        result = parse_publish_time_text("Feb 12, 2026 6:54 PM EST")
        assert result is not None
        assert result.year == 2026
        assert result.month == 2
        assert result.day == 12

    def test_english_month_no_tz(self):
        result = parse_publish_time_text("Mar 1, 2026 10:00 AM")
        assert result is not None
        assert result.year == 2026
        assert result.month == 3

    def test_english_month_pst(self):
        result = parse_publish_time_text("Jan 5, 2026 3:00 PM PST")
        assert result is not None
        assert result.year == 2026

    def test_unparseable_returns_none(self):
        assert parse_publish_time_text("not a date") is None

    def test_whitespace_cleaning(self):
        result = parse_publish_time_text("  2025-06-15   10:30:00  ")
        assert result is not None


# ---------------------------------------------------------------------------
# HTML extraction helpers
# ---------------------------------------------------------------------------

class TestExtractMetaPublishTime:

    def test_article_published_time(self):
        from bs4 import BeautifulSoup

        html = '<html><head><meta property="article:published_time" content="2025-06-15 10:00:00"></head></html>'
        soup = BeautifulSoup(html, "lxml")
        result = _extract_meta_publish_time(soup)
        assert result is not None
        assert result.year == 2025

    def test_no_meta_returns_none(self):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup("<html><head></head></html>", "lxml")
        assert _extract_meta_publish_time(soup) is None

    def test_empty_content_skipped(self):
        from bs4 import BeautifulSoup

        html = '<html><head><meta property="article:published_time" content=""></head></html>'
        soup = BeautifulSoup(html, "lxml")
        assert _extract_meta_publish_time(soup) is None


class TestExtractJsonldPublishTime:

    def test_date_published_in_jsonld(self):
        from bs4 import BeautifulSoup

        html = '''<html><head><script type="application/ld+json">
        {"datePublished": "2025-06-15 12:00:00"}
        </script></head></html>'''
        soup = BeautifulSoup(html, "lxml")
        result = _extract_jsonld_publish_time(soup)
        assert result is not None
        assert result.year == 2025

    def test_jsonld_array(self):
        from bs4 import BeautifulSoup

        html = '''<html><head><script type="application/ld+json">
        [{"datePublished": "2025-01-01 00:00:00"}]
        </script></head></html>'''
        soup = BeautifulSoup(html, "lxml")
        result = _extract_jsonld_publish_time(soup)
        assert result is not None

    def test_invalid_json_skipped(self):
        from bs4 import BeautifulSoup

        html = '<html><head><script type="application/ld+json">not json</script></head></html>'
        soup = BeautifulSoup(html, "lxml")
        assert _extract_jsonld_publish_time(soup) is None

    def test_no_date_fields(self):
        from bs4 import BeautifulSoup

        html = '''<html><head><script type="application/ld+json">
        {"name": "test"}
        </script></head></html>'''
        soup = BeautifulSoup(html, "lxml")
        assert _extract_jsonld_publish_time(soup) is None

    def test_empty_script(self):
        from bs4 import BeautifulSoup

        html = '<html><head><script type="application/ld+json"></script></head></html>'
        soup = BeautifulSoup(html, "lxml")
        assert _extract_jsonld_publish_time(soup) is None

    def test_non_dict_items_skipped(self):
        from bs4 import BeautifulSoup

        html = '''<html><head><script type="application/ld+json">
        ["string_item", 42]
        </script></head></html>'''
        soup = BeautifulSoup(html, "lxml")
        assert _extract_jsonld_publish_time(soup) is None

    def test_date_value_not_string_skipped(self):
        from bs4 import BeautifulSoup

        html = '''<html><head><script type="application/ld+json">
        {"datePublished": 12345}
        </script></head></html>'''
        soup = BeautifulSoup(html, "lxml")
        assert _extract_jsonld_publish_time(soup) is None


class TestExtractTimeTagPublishTime:

    def test_time_tag_datetime_attr(self):
        from bs4 import BeautifulSoup

        html = '<html><body><time datetime="2025-06-15 08:00:00">June 15</time></body></html>'
        soup = BeautifulSoup(html, "lxml")
        result = _extract_time_tag_publish_time(soup)
        assert result is not None
        assert result.year == 2025

    def test_time_tag_text_content(self):
        from bs4 import BeautifulSoup

        html = '<html><body><time>2025-06-15</time></body></html>'
        soup = BeautifulSoup(html, "lxml")
        result = _extract_time_tag_publish_time(soup)
        assert result is not None

    def test_no_time_tag(self):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup("<html><body></body></html>", "lxml")
        assert _extract_time_tag_publish_time(soup) is None

    def test_time_tag_empty_text_and_no_attr(self):
        from bs4 import BeautifulSoup

        html = '<html><body><time></time></body></html>'
        soup = BeautifulSoup(html, "lxml")
        assert _extract_time_tag_publish_time(soup) is None


class TestExtractLabeledPublishTime:

    def test_chinese_label(self):
        html = '<div>发布时间：2025-06-15 10:30:00</div>'
        result = _extract_labeled_publish_time(html)
        assert result is not None
        assert result.year == 2025

    def test_english_label(self):
        html = '<div>Published: Feb 12, 2026 6:54 PM EST</div>'
        result = _extract_labeled_publish_time(html)
        assert result is not None
        assert result.year == 2026

    def test_no_label_returns_none(self):
        html = '<div>Just some text</div>'
        assert _extract_labeled_publish_time(html) is None


class TestExtractPublishTimeFromHtml:

    def test_empty_html(self):
        assert extract_publish_time_from_html("") is None
        assert extract_publish_time_from_html(None) is None

    def test_meta_tag_priority(self):
        html = '''<html><head>
        <meta property="article:published_time" content="2025-06-15 10:00:00">
        </head><body><time datetime="2024-01-01">old</time></body></html>'''
        result = extract_publish_time_from_html(html)
        assert result is not None
        assert result.year == 2025

    def test_falls_through_to_labeled(self):
        html = '<html><head></head><body>发布时间：2025-06-15 10:30:00</body></html>'
        result = extract_publish_time_from_html(html)
        assert result is not None


class TestFetchPublishTimeFromUrl:

    @pytest.mark.asyncio
    async def test_successful_fetch(self):
        html = '<html><head><meta property="article:published_time" content="2025-06-15 10:00:00"></head></html>'

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.text = AsyncMock(return_value=html)

        mock_get_ctx = AsyncMock()
        mock_get_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_get_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_get_ctx)

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.utils.publish_time.aiohttp.ClientSession", return_value=mock_session_ctx):
            result = await fetch_publish_time_from_url("https://example.com/article")
        assert result is not None

    @pytest.mark.asyncio
    async def test_non_200_returns_none(self):
        with patch("app.utils.publish_time.aiohttp.ClientSession") as mock_cls:
            mock_resp = AsyncMock()
            mock_resp.status = 404

            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)

            mock_session = AsyncMock()
            mock_session.get.return_value = mock_ctx

            mock_session_ctx = AsyncMock()
            mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_session_ctx

            result = await fetch_publish_time_from_url("https://example.com/404")
        assert result is None

    @pytest.mark.asyncio
    async def test_exception_returns_none(self):
        with patch("app.utils.publish_time.aiohttp.ClientSession", side_effect=Exception("network error")):
            result = await fetch_publish_time_from_url("https://example.com/fail")
        assert result is None
