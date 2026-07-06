"""Tests for app.collectors.base — BaseCollector helpers."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from app.collectors.base import BaseCollector


class ConcreteCollector(BaseCollector):
    """Minimal concrete subclass for testing."""

    async def fetch(self, source) -> List[Dict[str, Any]]:
        return []


class TestBaseCollectorAuth:

    def test_get_runtime_auth_with_attr(self):
        collector = ConcreteCollector()
        source = MagicMock()
        source._runtime_auth = {"credentials": {"cookies": {"a": "1"}}}
        assert collector.get_runtime_auth(source) == {"credentials": {"cookies": {"a": "1"}}}

    def test_get_runtime_auth_missing_attr(self):
        collector = ConcreteCollector()
        source = MagicMock(spec=[])
        assert collector.get_runtime_auth(source) == {}

    def test_get_runtime_auth_non_dict(self):
        collector = ConcreteCollector()
        source = MagicMock()
        source._runtime_auth = "not-a-dict"
        assert collector.get_runtime_auth(source) == {}

    def test_get_runtime_cookies(self):
        collector = ConcreteCollector()
        source = MagicMock()
        source._runtime_auth = {"credentials": {"cookies": {"session": "abc"}}}
        cookies = collector.get_runtime_cookies(source)
        assert cookies == {"session": "abc"}

    def test_get_runtime_cookies_no_credentials(self):
        collector = ConcreteCollector()
        source = MagicMock()
        source._runtime_auth = {}
        cookies = collector.get_runtime_cookies(source)
        assert cookies == {}

    def test_get_runtime_browser_session(self):
        collector = ConcreteCollector()
        source = MagicMock()
        source._runtime_auth = {"browser_session": {"storage_state": "data"}}
        result = collector.get_runtime_browser_session(source)
        assert result == {"storage_state": "data"}

    def test_get_runtime_browser_session_missing(self):
        collector = ConcreteCollector()
        source = MagicMock()
        source._runtime_auth = {}
        result = collector.get_runtime_browser_session(source)
        assert result == {}

    def test_get_runtime_browser_session_non_dict(self):
        collector = ConcreteCollector()
        source = MagicMock()
        source._runtime_auth = {"browser_session": "not-dict"}
        result = collector.get_runtime_browser_session(source)
        assert result == {}

    def test_get_runtime_browser_session_from_imported_storage_state(self, tmp_path):
        storage_state = tmp_path / "storage_state.json"
        storage_state.write_text("{}", encoding="utf-8")
        collector = ConcreteCollector()
        source = MagicMock()
        source._runtime_auth = {"credentials": {"storage_state_path": str(storage_state)}}
        result = collector.get_runtime_browser_session(source)
        assert result["storage_state_path"] == str(storage_state)
        assert result["storage_state_exists"] is True
        assert result["auth_ready"] is True

    def test_get_runtime_browser_session_from_missing_imported_storage_state(self, tmp_path):
        collector = ConcreteCollector()
        source = MagicMock()
        source._runtime_auth = {"credentials": {"storage_state_path": str(tmp_path / "missing.json")}}
        result = collector.get_runtime_browser_session(source)
        assert result["auth_ready"] is False
        assert "storage_state" in result["auth_warning"]


class TestShouldFetch:

    @pytest.mark.asyncio
    async def test_should_fetch_never_fetched(self):
        collector = ConcreteCollector()
        source = MagicMock()
        source.last_fetched_at = None
        assert await collector.should_fetch(source) is True

    @pytest.mark.asyncio
    async def test_should_fetch_interval_elapsed(self):
        collector = ConcreteCollector()
        source = MagicMock()
        source.last_fetched_at = datetime(2020, 1, 1)
        source.fetch_interval = 30
        with patch("app.domains.fetch.collectors.base.utcnow_naive", return_value=datetime(2020, 1, 1, 1, 0)):
            assert await collector.should_fetch(source) is True

    @pytest.mark.asyncio
    async def test_should_fetch_interval_not_elapsed(self):
        collector = ConcreteCollector()
        source = MagicMock()
        source.last_fetched_at = datetime(2020, 1, 1, 0, 0)
        source.fetch_interval = 60
        with patch("app.domains.fetch.collectors.base.utcnow_naive", return_value=datetime(2020, 1, 1, 0, 30)):
            assert await collector.should_fetch(source) is False


class TestFilterNewContent:

    def test_no_last_content_id_returns_all(self):
        collector = ConcreteCollector()
        contents = [{"external_id": "a"}, {"external_id": "b"}]
        assert collector.filter_new_content(contents, None) == contents

    def test_marker_not_found_returns_all(self):
        collector = ConcreteCollector()
        contents = [{"external_id": "a"}, {"external_id": "b"}]
        assert collector.filter_new_content(contents, "c") == contents

    def test_descending_order_returns_before_marker(self):
        collector = ConcreteCollector()
        contents = [
            {"external_id": "c", "publish_time": datetime(2025, 3, 1)},
            {"external_id": "b", "publish_time": datetime(2025, 2, 1)},
            {"external_id": "a", "publish_time": datetime(2025, 1, 1)},
        ]
        result = collector.filter_new_content(contents, "b")
        assert len(result) == 1
        assert result[0]["external_id"] == "c"

    def test_ascending_order_returns_after_marker(self):
        collector = ConcreteCollector()
        contents = [
            {"external_id": "a", "publish_time": datetime(2025, 1, 1)},
            {"external_id": "b", "publish_time": datetime(2025, 2, 1)},
            {"external_id": "c", "publish_time": datetime(2025, 3, 1)},
        ]
        result = collector.filter_new_content(contents, "b")
        assert len(result) == 1
        assert result[0]["external_id"] == "c"

    def test_marker_at_beginning_no_timestamps(self):
        collector = ConcreteCollector()
        contents = [{"external_id": "a"}, {"external_id": "b"}, {"external_id": "c"}]
        result = collector.filter_new_content(contents, "a")
        assert len(result) == 2
        assert result[0]["external_id"] == "b"

    def test_marker_in_middle_no_timestamps(self):
        collector = ConcreteCollector()
        contents = [{"external_id": "a"}, {"external_id": "b"}, {"external_id": "c"}]
        result = collector.filter_new_content(contents, "b")
        assert len(result) == 1
        assert result[0]["external_id"] == "a"

    def test_string_datetime_parsing(self):
        collector = ConcreteCollector()
        contents = [
            {"external_id": "c", "publish_time": "2025-03-01T00:00:00Z"},
            {"external_id": "b", "publish_time": "2025-02-01T00:00:00Z"},
            {"external_id": "a", "publish_time": "2025-01-01T00:00:00Z"},
        ]
        result = collector.filter_new_content(contents, "b")
        assert len(result) == 1
        assert result[0]["external_id"] == "c"

    def test_invalid_datetime_string(self):
        collector = ConcreteCollector()
        contents = [
            {"external_id": "a", "publish_time": "not-a-date"},
            {"external_id": "b", "publish_time": "also-not"},
        ]
        result = collector.filter_new_content(contents, "a")
        assert len(result) == 1
        assert result[0]["external_id"] == "b"


class TestValidateContent:

    def test_valid_content(self):
        collector = ConcreteCollector()
        assert collector.validate_content({"title": "Test", "url": "https://example.com"}) is True

    def test_missing_title(self):
        collector = ConcreteCollector()
        assert collector.validate_content({"url": "https://example.com"}) is False

    def test_missing_url(self):
        collector = ConcreteCollector()
        assert collector.validate_content({"title": "Test"}) is False

    def test_empty_title(self):
        collector = ConcreteCollector()
        assert collector.validate_content({"title": "", "url": "https://example.com"}) is False

    def test_both_missing(self):
        collector = ConcreteCollector()
        assert collector.validate_content({}) is False


class TestCheckSsrf:

    @pytest.mark.asyncio
    async def test_check_ssrf_delegates(self):
        collector = ConcreteCollector()
        with patch("app.domains.fetch.collectors.base.assert_public_http_target") as mock_check:
            mock_check.return_value = None
            await collector._check_ssrf("https://example.com")
            mock_check.assert_called_once_with("https://example.com")
