"""Tests for pipeline stages: CollectorStage, StorageStage, coordinator, dedupe.

Phase 7 retired :mod:`app.pipeline.ai_stage` (the legacy deprecated stage
had no production callers; the tests that pinned it were removed alongside
the implementation).
"""

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.content import Content
from app.models.source import Source, SourceType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_source(**overrides) -> MagicMock:
    s = MagicMock(spec=Source)
    s.id = str(uuid4())
    s.name = "Test Source"
    s.url = "https://example.com"
    s.type = SourceType.RSS
    s.auth_config_id = None
    s.auth_config = None
    s.last_content_id = None
    s.error_count = 0
    s.last_error = None
    s.metadata_ = {}
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _raw(title="Article", url="https://example.com/1", external_id="ext-1", **extra):
    d = {"title": title, "url": url, "external_id": external_id, "content": "body text", "publish_time": datetime.utcnow().isoformat()}
    d.update(extra)
    return d


def _build_sync_db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


# ===========================================================================
# CollectorStage
# ===========================================================================

class TestCollectorStage:

    @pytest.mark.asyncio
    async def test_fetches_from_primary_url(self):
        """CollectorStage should call collector.fetch for the source URL."""
        from app.domains.fetch.collector_stage import CollectorStage

        source = _make_source(type=SourceType.RSS)
        source.auth_config = None
        source.auth_config_id = None

        mock_collector = MagicMock()
        mock_collector.fetch = AsyncMock(return_value=[_raw()])
        mock_collector.filter_new_content = MagicMock(side_effect=lambda items, _: items)

        db = MagicMock()

        with patch("app.domains.fetch.collector_stage.get_collector", return_value=mock_collector), \
             patch("app.domains.fetch.collector_stage.get_source_urls", return_value=["https://example.com"]), \
             patch("app.domains.fetch.collector_stage.dedupe_raw_contents", side_effect=lambda x: x), \
             patch("app.domains.fetch.collector_stage.auth_warning_entry", return_value=None), \
             patch("app.domains.fetch.collector_stage.cookie_hydration_warning_entry", return_value=None), \
             patch("app.domains.fetch.collector_stage.merge_warning_messages", return_value=None):

            raw, warning, primary = await CollectorStage.execute(db, source)

        assert len(raw) == 1
        mock_collector.fetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_fetch_error_gracefully(self):
        """All URLs failing must surface a fetch_failed error, not silent success."""
        from app.domains.fetch.collector_stage import CollectorStage

        source = _make_source(type=SourceType.RSS)
        source.auth_config = None
        source.auth_config_id = None

        mock_collector = MagicMock()
        mock_collector.fetch = AsyncMock(side_effect=RuntimeError("network"))

        db = MagicMock()

        with patch("app.domains.fetch.collector_stage.get_collector", return_value=mock_collector), \
             patch("app.domains.fetch.collector_stage.get_source_urls", return_value=["https://example.com"]), \
             patch("app.domains.fetch.collector_stage.dedupe_raw_contents", side_effect=lambda x: x), \
             patch("app.domains.fetch.collector_stage.auth_warning_entry", return_value=None), \
             patch("app.domains.fetch.collector_stage.cookie_hydration_warning_entry", return_value=None), \
             patch("app.domains.fetch.collector_stage.merge_warning_messages", side_effect=lambda *a: next((m for m in a if m), None)):

            raw, warning, primary = await CollectorStage.execute(db, source)

        assert raw == []
        assert primary is not None
        # A bare RuntimeError can't be classified further -> unified "unknown".
        assert primary[0] == "unknown"
        assert primary[1] == "error"

    @pytest.mark.asyncio
    async def test_fetch_failure_is_classified_with_structured_code(self):
        """A classifiable fetch exception surfaces its taxonomy code, not 'fetch_failed'."""
        from app.domains.fetch.collector_stage import CollectorStage

        source = _make_source(type=SourceType.RSS)
        source.auth_config = None
        source.auth_config_id = None

        mock_collector = MagicMock()
        mock_collector.fetch = AsyncMock(
            side_effect=ValueError("private address is not allowed: 10.0.0.1")
        )

        db = MagicMock()

        with patch("app.domains.fetch.collector_stage.get_collector", return_value=mock_collector), \
             patch("app.domains.fetch.collector_stage.get_source_urls", return_value=["https://example.com"]), \
             patch("app.domains.fetch.collector_stage.dedupe_raw_contents", side_effect=lambda x: x), \
             patch("app.domains.fetch.collector_stage.auth_warning_entry", return_value=None), \
             patch("app.domains.fetch.collector_stage.cookie_hydration_warning_entry", return_value=None), \
             patch("app.domains.fetch.collector_stage.merge_warning_messages", side_effect=lambda *a: next((m for m in a if m), None)):

            raw, warning, primary = await CollectorStage.execute(db, source)

        assert raw == []
        assert primary is not None
        assert primary[0] == "ssrf_blocked"
        assert primary[1] == "error"

    @pytest.mark.asyncio
    async def test_partial_fetch_failure_is_not_flagged_as_error(self):
        """One URL failing while another succeeds must not be flagged fetch_failed."""
        from app.domains.fetch.collector_stage import CollectorStage

        source = _make_source(type=SourceType.RSS)
        source.auth_config = None
        source.auth_config_id = None

        async def _fetch(src):
            if src.url == "https://bad.com":
                raise RuntimeError("network")
            return [_raw()]

        mock_collector = MagicMock()
        mock_collector.fetch = AsyncMock(side_effect=_fetch)
        mock_collector.filter_new_content = MagicMock(side_effect=lambda items, _: items)

        db = MagicMock()

        with patch("app.domains.fetch.collector_stage.get_collector", return_value=mock_collector), \
             patch("app.domains.fetch.collector_stage.get_source_urls", return_value=["https://bad.com", "https://ok.com"]), \
             patch("app.domains.fetch.collector_stage.dedupe_raw_contents", side_effect=lambda x: x), \
             patch("app.domains.fetch.collector_stage.auth_warning_entry", return_value=None), \
             patch("app.domains.fetch.collector_stage.cookie_hydration_warning_entry", return_value=None), \
             patch("app.domains.fetch.collector_stage.merge_warning_messages", side_effect=lambda *a: next((m for m in a if m), None)):

            raw, warning, primary = await CollectorStage.execute(db, source)

        assert len(raw) == 1
        assert primary is None

    @pytest.mark.asyncio
    async def test_multiple_urls_concatenated(self):
        """CollectorStage should fetch from multiple source URLs and combine results."""
        from app.domains.fetch.collector_stage import CollectorStage

        source = _make_source(type=SourceType.RSS)
        source.auth_config = None
        source.auth_config_id = None

        call_count = 0

        async def _fetch(src):
            nonlocal call_count
            call_count += 1
            return [_raw(external_id=f"ext-{call_count}")]

        mock_collector = MagicMock()
        mock_collector.fetch = AsyncMock(side_effect=_fetch)
        mock_collector.filter_new_content = MagicMock(side_effect=lambda items, _: items)

        db = MagicMock()

        with patch("app.domains.fetch.collector_stage.get_collector", return_value=mock_collector), \
             patch("app.domains.fetch.collector_stage.get_source_urls", return_value=["https://a.com", "https://b.com"]), \
             patch("app.domains.fetch.collector_stage.dedupe_raw_contents", side_effect=lambda x: x), \
             patch("app.domains.fetch.collector_stage.auth_warning_entry", return_value=None), \
             patch("app.domains.fetch.collector_stage.cookie_hydration_warning_entry", return_value=None), \
             patch("app.domains.fetch.collector_stage.merge_warning_messages", return_value=None):

            raw, _, _ = await CollectorStage.execute(db, source)

        assert len(raw) == 2
        assert mock_collector.fetch.call_count == 2

    @pytest.mark.asyncio
    async def test_youtube_channel_id_marker_does_not_filter_videos(self):
        """A stored YouTube channel ID is source state, not a fetched content marker."""
        from app.domains.fetch.collector_stage import CollectorStage

        source = _make_source(
            type=SourceType.YOUTUBE,
            last_content_id="UCSHZKyawb77ixDdsGog4iWA",
            url="https://www.youtube.com/c/lexfridman",
        )
        source.auth_config = None
        source.auth_config_id = None

        mock_collector = MagicMock()
        mock_collector.fetch = AsyncMock(
            return_value=[
                _raw(title="Video 1", url="https://www.youtube.com/watch?v=pv1TUJSEM2k", external_id="pv1TUJSEM2k"),
                _raw(title="Video 2", url="https://www.youtube.com/watch?v=1M3Vdl6DRkU", external_id="1M3Vdl6DRkU"),
            ]
        )
        mock_collector.filter_new_content = MagicMock(side_effect=AssertionError("should not filter channel marker"))

        db = MagicMock()

        with patch("app.domains.fetch.collector_stage.get_collector", return_value=mock_collector), \
             patch("app.domains.fetch.collector_stage.get_source_urls", return_value=["https://www.youtube.com/c/lexfridman"]), \
             patch("app.domains.fetch.collector_stage.dedupe_raw_contents", side_effect=lambda x: x), \
             patch("app.domains.fetch.collector_stage.auth_warning_entry", return_value=None), \
             patch("app.domains.fetch.collector_stage.cookie_hydration_warning_entry", return_value=None), \
             patch("app.domains.fetch.collector_stage.merge_warning_messages", return_value=None):

            raw, _, _ = await CollectorStage.execute(db, source)

        assert [item["external_id"] for item in raw] == ["pv1TUJSEM2k", "1M3Vdl6DRkU"]
        mock_collector.filter_new_content.assert_not_called()

    @pytest.mark.asyncio
    async def test_auth_config_auto_bind_for_website(self):
        """When type is website and no auth_config_id, it should try to auto-bind."""
        from app.domains.fetch.collector_stage import CollectorStage

        source = _make_source(type="website")
        source.type = MagicMock()
        source.type.value = "website"
        source.auth_config = None
        source.auth_config_id = None
        source.url = "https://example.com/page"

        mock_collector = MagicMock()
        mock_collector.fetch = AsyncMock(return_value=[])

        db = MagicMock()
        db.query.return_value.all.return_value = []

        with patch("app.domains.fetch.collector_stage.get_collector", return_value=mock_collector), \
             patch("app.domains.fetch.collector_stage.get_source_urls", return_value=["https://example.com/page"]), \
             patch("app.domains.fetch.collector_stage.dedupe_raw_contents", side_effect=lambda x: x), \
             patch("app.domains.fetch.collector_stage.auth_warning_entry", return_value=None), \
             patch("app.domains.fetch.collector_stage.cookie_hydration_warning_entry", return_value=None), \
             patch("app.domains.fetch.collector_stage.merge_warning_messages", return_value=None), \
             patch("app.domains.fetch.collector_stage.url_utils") as mock_url:

            mock_url.normalize_host.return_value = "example.com"
            raw, _, _ = await CollectorStage.execute(db, source)

        db.query.assert_called()

    @pytest.mark.asyncio
    async def test_active_browser_session_skips_password_auto_login(self):
        """An active browser_session's on-disk profile already holds valid cookies;
        running password auto-login anyway (WSJ et al.) only yields false-positive
        ``auth_captcha`` warnings. Verify the stage short-circuits it."""
        from app.domains.fetch.collector_stage import CollectorStage

        source = _make_source(type="website")
        source.type = MagicMock()
        source.type.value = "website"
        source.auth_config_id = uuid4()
        auth_cfg = MagicMock()
        auth_cfg.auth_type = MagicMock()
        auth_cfg.auth_type.value = "password"
        auth_cfg.login_url = "https://example.com/login"
        auth_cfg.login_selectors = {}
        source.auth_config = auth_cfg

        mock_collector = MagicMock()
        mock_collector.fetch = AsyncMock(return_value=[])
        db = MagicMock()

        refresh_mock = AsyncMock(return_value=({}, None))
        browser_session_stub = {
            "id": "abc",
            "user_data_dir": "/tmp/p",
            "status": "active",
            "auth_ready": True,
        }

        with patch("app.domains.fetch.collector_stage.get_collector", return_value=mock_collector), \
             patch("app.domains.fetch.collector_stage.get_source_urls", return_value=["https://example.com/x"]), \
             patch("app.domains.fetch.collector_stage.dedupe_raw_contents", side_effect=lambda x: x), \
             patch("app.domains.fetch.collector_stage.auth_warning_entry", return_value=None), \
             patch("app.domains.fetch.collector_stage.cookie_hydration_warning_entry", return_value=None), \
             patch("app.domains.fetch.collector_stage.merge_warning_messages", return_value=None), \
             patch("app.domains.fetch.collector_stage.try_parse_auth_credentials", return_value={"username": "u", "password": "p"}), \
             patch("app.domains.fetch.collector_stage.maybe_refresh_auth_cookies", refresh_mock), \
             patch(
                 "app.domains.fetch.collector_stage.build_browser_session_runtime",
                 return_value=browser_session_stub,
             ):

            await CollectorStage.execute(db, source)

        refresh_mock.assert_not_awaited()
        runtime_auth = getattr(source, "_runtime_auth")
        assert runtime_auth["browser_session"] == browser_session_stub

    @pytest.mark.asyncio
    async def test_unvalidated_browser_session_skips_password_auto_login_by_default(self):
        """A bound browser session is the preferred auth carrier. Password
        auto-login is opt-in via metadata.allow_password_login."""
        from app.domains.fetch.collector_stage import CollectorStage

        source = _make_source(type="website")
        source.type = MagicMock()
        source.type.value = "website"
        source.auth_config_id = uuid4()
        auth_cfg = MagicMock()
        auth_cfg.auth_type = MagicMock()
        auth_cfg.auth_type.value = "password"
        auth_cfg.login_url = "https://example.com/login"
        auth_cfg.login_selectors = {}
        source.auth_config = auth_cfg

        mock_collector = MagicMock()
        mock_collector.fetch = AsyncMock(return_value=[])
        db = MagicMock()

        refresh_mock = AsyncMock(return_value=({"cookies": {"x": "y"}}, None))
        browser_session_stub = {
            "id": "abc",
            "user_data_dir": "/tmp/p",
            "status": "active",
            "auth_ready": False,
            "auth_warning": "浏览器会话尚未完成正文校验，需要重新登录或校验",
        }

        with patch("app.domains.fetch.collector_stage.get_collector", return_value=mock_collector), \
             patch("app.domains.fetch.collector_stage.get_source_urls", return_value=["https://example.com/x"]), \
             patch("app.domains.fetch.collector_stage.dedupe_raw_contents", side_effect=lambda x: x), \
             patch("app.domains.fetch.collector_stage.auth_warning_entry", return_value=None), \
             patch("app.domains.fetch.collector_stage.cookie_hydration_warning_entry", return_value=None), \
             patch("app.domains.fetch.collector_stage.merge_warning_messages", return_value=None), \
             patch("app.domains.fetch.collector_stage.try_parse_auth_credentials", return_value={"username": "u", "password": "p"}), \
             patch("app.domains.fetch.collector_stage.maybe_refresh_auth_cookies", refresh_mock), \
             patch(
                 "app.domains.fetch.collector_stage.build_browser_session_runtime",
                 return_value=browser_session_stub,
             ):

            await CollectorStage.execute(db, source)

        refresh_mock.assert_not_awaited()
        runtime_auth = getattr(source, "_runtime_auth")
        assert runtime_auth["credentials"] == {"username": "u", "password": "p"}

    @pytest.mark.asyncio
    async def test_allow_password_login_allows_browser_session_fallback(self):
        """Sources can opt into password fallback when the bound browser
        session is stale or not yet validated."""
        from app.domains.fetch.collector_stage import CollectorStage

        source = _make_source(type="website")
        source.type = MagicMock()
        source.type.value = "website"
        source.metadata_ = {"allow_password_login": True}
        source.auth_config_id = uuid4()
        auth_cfg = MagicMock()
        auth_cfg.auth_type = MagicMock()
        auth_cfg.auth_type.value = "password"
        auth_cfg.login_url = "https://example.com/login"
        auth_cfg.login_selectors = {}
        source.auth_config = auth_cfg

        mock_collector = MagicMock()
        mock_collector.fetch = AsyncMock(return_value=[])
        db = MagicMock()

        refresh_mock = AsyncMock(return_value=({"cookies": {"x": "y"}}, None))
        browser_session_stub = {
            "id": "abc",
            "user_data_dir": "/tmp/p",
            "status": "needs_login",
            "auth_ready": False,
        }

        with patch("app.domains.fetch.collector_stage.get_collector", return_value=mock_collector), \
             patch("app.domains.fetch.collector_stage.get_source_urls", return_value=["https://example.com/x"]), \
             patch("app.domains.fetch.collector_stage.dedupe_raw_contents", side_effect=lambda x: x), \
             patch("app.domains.fetch.collector_stage.auth_warning_entry", return_value=None), \
             patch("app.domains.fetch.collector_stage.cookie_hydration_warning_entry", return_value=None), \
             patch("app.domains.fetch.collector_stage.merge_warning_messages", return_value=None), \
             patch("app.domains.fetch.collector_stage.try_parse_auth_credentials", return_value={"username": "u", "password": "p"}), \
             patch("app.domains.fetch.collector_stage.maybe_refresh_auth_cookies", refresh_mock), \
             patch(
                 "app.domains.fetch.collector_stage.build_browser_session_runtime",
                 return_value=browser_session_stub,
             ):

            await CollectorStage.execute(db, source)

        refresh_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_inactive_browser_session_skips_password_auto_login_by_default(self):
        """Even needs_login/error browser sessions keep password auto-login
        disabled unless the source explicitly opts into fallback."""
        from app.domains.fetch.collector_stage import CollectorStage

        source = _make_source(type="website")
        source.type = MagicMock()
        source.type.value = "website"
        source.auth_config_id = uuid4()
        auth_cfg = MagicMock()
        auth_cfg.auth_type = MagicMock()
        auth_cfg.auth_type.value = "password"
        auth_cfg.login_url = "https://example.com/login"
        auth_cfg.login_selectors = {}
        source.auth_config = auth_cfg

        mock_collector = MagicMock()
        mock_collector.fetch = AsyncMock(return_value=[])
        db = MagicMock()

        refresh_mock = AsyncMock(return_value=({"cookies": {"x": "y"}}, None))
        browser_session_stub = {
            "id": "abc",
            "user_data_dir": "/tmp/p",
            "status": "needs_login",
            "auth_ready": False,
        }

        with patch("app.domains.fetch.collector_stage.get_collector", return_value=mock_collector), \
             patch("app.domains.fetch.collector_stage.get_source_urls", return_value=["https://example.com/x"]), \
             patch("app.domains.fetch.collector_stage.dedupe_raw_contents", side_effect=lambda x: x), \
             patch("app.domains.fetch.collector_stage.auth_warning_entry", return_value=None), \
             patch("app.domains.fetch.collector_stage.cookie_hydration_warning_entry", return_value=None), \
             patch("app.domains.fetch.collector_stage.merge_warning_messages", return_value=None), \
             patch("app.domains.fetch.collector_stage.try_parse_auth_credentials", return_value={"username": "u", "password": "p"}), \
             patch("app.domains.fetch.collector_stage.maybe_refresh_auth_cookies", refresh_mock), \
             patch(
                 "app.domains.fetch.collector_stage.build_browser_session_runtime",
                 return_value=browser_session_stub,
             ):

            await CollectorStage.execute(db, source)

        refresh_mock.assert_not_awaited()


# ===========================================================================
# StorageStage
# ===========================================================================

class TestStorageStage:

    def test_saves_contents_and_returns_count(self):
        from app.domains.ingest.storage import StorageStage

        c1 = MagicMock(spec=Content)
        c1.external_id = "ext-1"
        c1.original_url = "https://example.com/1"
        c2 = MagicMock(spec=Content)
        c2.external_id = "ext-2"
        c2.original_url = "https://example.com/2"

        db = MagicMock()
        nested_ctx = MagicMock()
        db.begin_nested.return_value = nested_ctx
        db.query.return_value.filter.return_value.filter.return_value.first.return_value = None
        nested_ctx.__enter__ = MagicMock(return_value=nested_ctx)
        nested_ctx.__exit__ = MagicMock(return_value=False)

        with patch("app.domains.ingest.storage.normalize_external_id", side_effect=lambda x: x):
            result = StorageStage.execute(db, [c1, c2])

        assert result.saved_count == 2
        assert result.requested_count == 2
        assert len(result.postprocess_candidates) == 2
        assert db.add.call_count == 2

    def test_skips_integrity_error(self):
        from sqlalchemy.exc import IntegrityError
        from app.domains.ingest.storage import StorageStage

        c1 = MagicMock(spec=Content)
        c1.external_id = "dup"
        c1.original_url = "https://example.com/dup"

        db = MagicMock()
        nested_ctx = MagicMock()
        db.begin_nested.return_value = nested_ctx
        nested_ctx.__enter__ = MagicMock(return_value=nested_ctx)
        nested_ctx.__exit__ = MagicMock(return_value=False)
        db.add.side_effect = IntegrityError("dup", {}, None)
        existing = MagicMock(spec=Content)
        existing.id = "existing-id"
        first = db.query.return_value.filter.return_value.filter.return_value.first
        first.side_effect = [None, existing]

        with patch("app.domains.ingest.storage.normalize_external_id", side_effect=lambda x: x):
            result = StorageStage.execute(db, [c1])

        assert result.saved_count == 0
        assert result.unchanged_duplicate_count == 1
        assert result.outcome.value == "success"

    def test_empty_contents_returns_zero(self):
        from app.domains.ingest.storage import StorageStage

        db = MagicMock()
        result = StorageStage.execute(db, [])

        assert result.saved_count == 0
        assert result.latest_saved_marker is None

    def test_marker_from_first_saved(self):
        from app.domains.ingest.storage import StorageStage

        c1 = MagicMock(spec=Content)
        c1.external_id = "first-id"
        c1.original_url = "https://example.com/1"

        db = MagicMock()
        nested_ctx = MagicMock()
        db.begin_nested.return_value = nested_ctx
        db.query.return_value.filter.return_value.filter.return_value.first.return_value = None
        nested_ctx.__enter__ = MagicMock(return_value=nested_ctx)
        nested_ctx.__exit__ = MagicMock(return_value=False)

        with patch("app.domains.ingest.storage.normalize_external_id", return_value="first-id"):
            result = StorageStage.execute(db, [c1])

        assert result.saved_count == 1
        assert result.latest_saved_marker == "first-id"


# ===========================================================================
# domains.ingest.build_content.build_raw_content_objects
# (Phase 3 step 3 moved this here; the fetch coordinator now imports the
# canonical helper directly.)
# ===========================================================================

_no_reject = patch("app.domains.ingest.build_content.get_non_article_format_reject_reason", return_value=None)


class TestBuildRawContentObjects:

    @pytest.mark.asyncio
    async def test_basic_content_creation(self):
        from app.domains.ingest.build_content import build_raw_content_objects

        source = _make_source(use_keyword_filter=False)
        raw = [_raw(title="Hello World", content="Some body text")]

        with _no_reject, patch("app.domains.ingest.extractor.ContentExtractor") as MockExt:
            MockExt.return_value = AsyncMock()
            results, _build_failures = await build_raw_content_objects(raw, source)

        assert len(results) == 1
        assert results[0].title == "Hello World"
        assert results[0].source_id == source.id

    @pytest.mark.asyncio
    async def test_html_extraction_when_no_content(self):
        from app.domains.ingest.build_content import build_raw_content_objects

        source = _make_source()
        raw = [{"title": "T", "url": "https://example.com", "html": "<p>Extracted</p>", "content": "", "publish_time": datetime.utcnow().isoformat()}]

        mock_extractor = AsyncMock()
        mock_extractor.extract.return_value = "Extracted text"

        with _no_reject, patch("app.domains.ingest.extractor.ContentExtractor", return_value=mock_extractor):
            results, _build_failures = await build_raw_content_objects(raw, source)

        assert len(results) == 1
        mock_extractor.extract.assert_called_once()

    @pytest.mark.asyncio
    async def test_wallstreetcn_structured_article_uses_page_heading_as_title(self):
        from app.domains.ingest.build_content import build_raw_content_objects

        source = _make_source()
        body = "华尔街见闻正文内容。" * 30
        raw = [_raw(
            title="正文标题 作者 10:28",
            content="",
            html=(
                "<article><header><h1>正文标题</h1>"
                "<time datetime='2026-07-31T07:53:59.000Z'>07:53</time></header>"
                f"<section class='articleBody'>{body}</section></article>"
            ),
        )]

        with _no_reject, patch("app.domains.ingest.extractor.ContentExtractor") as MockExt:
            MockExt.return_value = AsyncMock()
            results, failures = await build_raw_content_objects(raw, source)

        assert failures == 0
        assert results[0].title == "正文标题"
        assert results[0].full_content == body

    @pytest.mark.asyncio
    async def test_enabled_web_clean_preserves_markdown_structure_for_reader(self):
        from app.domains.fetch.web_clean.contracts import CleanResult
        from app.domains.ingest.build_content import build_raw_content_objects

        source = _make_source(type=SourceType.WEBSITE)
        source.metadata_ = {"web_clean_mode": "write"}
        markdown = (
            "## Section heading\n\n"
            "[Source link](https://example.com/source)\n\n"
            "```python\nprint('kept')\n```"
        )
        clean_result = CleanResult(
            url="https://example.com/article",
            title="Structured article",
            author=None,
            published_time=None,
            canonical_url=None,
            site_name=None,
            language="en",
            article_html="<article><h2>Section heading</h2></article>",
            article_text="Section heading\n\nSource link\n\nprint('kept')",
            article_markdown=markdown,
            clean_full_html=None,
            extraction_method="beautifulsoup",
            template_id=None,
            quality_status="full",
            quality_score=0.9,
            trace={
                "selected_method": "beautifulsoup",
                "candidates": [{"method": "beautifulsoup", "rejected_reason": None}],
            },
        )
        mock_extractor = AsyncMock()
        mock_extractor.extract_clean.return_value = clean_result
        settings = MagicMock(
            pim_web_clean_enabled=True,
            pim_web_clean_shadow=False,
            pim_web_clean_template_enabled=True,
            pim_web_clean_max_html_bytes=3_000_000,
            pim_web_clean_timeout_ms=2_000,
            pim_web_clean_write_metadata=True,
        )
        raw = [
            _raw(
                title="Structured article",
                url="https://example.com/article",
                content="legacy plain body",
                html="<article><h2>Section heading</h2></article>",
            )
        ]

        with (
            _no_reject,
            patch("app.domains.ingest.extractor.ContentExtractor", return_value=mock_extractor),
            patch("app.domains.ingest.build_content.get_settings", return_value=settings),
        ):
            results, build_failures = await build_raw_content_objects(raw, source)

        assert build_failures == 0
        assert results[0].full_content == markdown
        assert results[0].summary == "Section heading\n\nSource link\n\nprint('kept')"

    @pytest.mark.asyncio
    async def test_short_cls_structured_body_is_stamped_as_trusted_fulltext(self):
        from app.domains.ingest.build_content import build_raw_content_objects

        title = "财联社7月28日电，上期所原油主力合约日内跌幅扩大至6%，报531.1元/桶。"
        html = f"""
        <html><body>
          <script id="__NEXT_DATA__" type="application/json">
          {{
            "props": {{
              "pageProps": {{
                "articleDetail": {{
                  "id": 2438608,
                  "title": {json.dumps(title, ensure_ascii=False)},
                  "content": {json.dumps(title, ensure_ascii=False)},
                  "ctime": 1785205935
                }}
              }}
            }}
          }}
          </script>
        </body></html>
        """
        source = _make_source(type=SourceType.WEBSITE, name="财联社")
        raw = [
            _raw(
                title=title,
                url="https://www.cls.cn/detail/2438608",
                content="",
                html=html,
                publish_time=None,
                metadata={"publish_time_estimated": True},
            )
        ]

        with _no_reject:
            results, build_failures = await build_raw_content_objects(raw, source)

        assert build_failures == 0
        assert len(results) == 1
        content = results[0]
        assert content.full_content == f"2026年07月28日 10:32:15\n\n{title}"
        assert content.metadata_["article_extract_method"] == "structured:cls_next_data"
        assert content.metadata_["fulltext_status"] == "full"
        assert content.publish_time.isoformat() == "2026-07-28T02:32:15+00:00"

    @pytest.mark.asyncio
    async def test_publish_time_iso_parsing(self):
        from app.domains.ingest.build_content import build_raw_content_objects

        source = _make_source()
        raw = [_raw(publish_time="2025-06-15T10:00:00Z")]

        with _no_reject, patch("app.domains.ingest.extractor.ContentExtractor") as MockExt:
            MockExt.return_value = AsyncMock()
            results, _build_failures = await build_raw_content_objects(raw, source)

        assert results[0].publish_time.year == 2025
        assert results[0].publish_time.month == 6

    @pytest.mark.asyncio
    async def test_html_metadata_backfills_canonical_and_publish_time(self):
        from app.domains.ingest.build_content import build_raw_content_objects

        source = _make_source(type=SourceType.WEBSITE)
        raw = [
            _raw(
                url="https://example.com/amp/story",
                content="",
                publish_time=None,
                html=(
                    '<html><head><link rel="canonical" href="https://example.com/news/story">'
                    '<meta property="article:published_time" content="2026-07-02T01:02:03Z">'
                    "</head><body><article>Article body from extractor.</article></body></html>"
                ),
                metadata={"publish_time_estimated": True},
            )
        ]
        mock_extractor = AsyncMock()
        mock_extractor.extract.return_value = "Article body from extractor. " * 20

        with _no_reject, patch("app.domains.ingest.extractor.ContentExtractor", return_value=mock_extractor):
            results, _build_failures = await build_raw_content_objects(raw, source)

        assert len(results) == 1
        assert results[0].metadata_["canonical_url"] == "https://example.com/news/story"
        assert results[0].metadata_["canonical_external_id"] == "https://example.com/news/story"
        assert results[0].metadata_["publish_time_source"] == "html_metadata"
        assert results[0].publish_time.year == 2026
        assert results[0].publish_time.hour == 1

    @pytest.mark.asyncio
    async def test_title_identity_metadata_is_stamped(self):
        from app.domains.ingest.build_content import build_raw_content_objects

        source = _make_source(use_keyword_filter=False)
        raw = [
            _raw(
                title="Central Bank Announces New Policy Framework",
                content="Substantial article body. " * 20,
                metadata={},
            )
        ]

        with _no_reject, patch("app.domains.ingest.extractor.ContentExtractor"):
            results, _build_failures = await build_raw_content_objects(raw, source)

        assert len(results) == 1
        title_fp = results[0].metadata_["title_fp"]
        assert len(title_fp) == 16
        assert results[0].metadata_["duplicate_group_id"] == f"title:{title_fp}"

    @pytest.mark.asyncio
    async def test_missing_publish_time_stays_null(self):
        from app.domains.ingest.build_content import build_raw_content_objects

        source = _make_source()
        raw = [_raw(publish_time=None)]

        with _no_reject, patch("app.domains.ingest.extractor.ContentExtractor") as MockExt:
            MockExt.return_value = AsyncMock()
            results, _build_failures = await build_raw_content_objects(raw, source)

        assert results[0].publish_time is None

    @pytest.mark.asyncio
    async def test_skips_items_on_error(self):
        from app.domains.ingest.build_content import build_raw_content_objects

        source = _make_source()
        raw = [_raw(), {"title": None}]

        with _no_reject, patch("app.domains.ingest.extractor.ContentExtractor") as MockExt:
            MockExt.return_value = AsyncMock()
            with patch("app.domains.ingest.build_content.strip_html_tags", side_effect=[
                "Article", "body text", RuntimeError("bad data")
            ]):
                results, _build_failures = await build_raw_content_objects(raw, source)

        assert len(results) <= 2

    @pytest.mark.asyncio
    async def test_summary_truncation(self):
        from app.domains.ingest.build_content import build_raw_content_objects

        source = _make_source()
        long_body = "X" * 600
        raw = [_raw(content=long_body)]

        with _no_reject, patch("app.domains.ingest.extractor.ContentExtractor") as MockExt:
            MockExt.return_value = AsyncMock()
            results, _build_failures = await build_raw_content_objects(raw, source)

        assert results[0].summary is not None
        assert results[0].summary.endswith("…")

    @pytest.mark.asyncio
    async def test_metadata_normalised_to_dict_and_quality_stamped(self):
        from app.domains.ingest.build_content import build_raw_content_objects

        source = _make_source()
        raw = [_raw(metadata="not-a-dict")]

        with _no_reject, patch("app.domains.ingest.extractor.ContentExtractor") as MockExt:
            MockExt.return_value = AsyncMock()
            results, _build_failures = await build_raw_content_objects(raw, source)

        assert isinstance(results[0].metadata_, dict)
        # Non-dict metadata is normalised to a dict and stamped with the
        # content-quality signals merge_content_quality_metadata produces.
        assert "content_quality" in results[0].metadata_
        assert results[0].metadata_.get("fulltext_status") == "title_only"


# ===========================================================================
# coordinator._update_source_status
# ===========================================================================

class TestUpdateSourceStatus:

    @pytest.mark.asyncio
    async def test_run_fetch_pipeline_records_collector_failure_status(self):
        from app.domains.fetch.coordinator import run_fetch_pipeline

        source = _make_source(error_count=0, enabled=True)
        source.metadata_ = {}
        db = MagicMock()

        with patch(
            "app.domains.fetch.collector_stage.CollectorStage.execute",
            new=AsyncMock(return_value=([], "too many requests", ("http_429", "error", "请求限流"))),
        ):
            result = await run_fetch_pipeline(db, source, manual_trigger=False)

        assert result == {"status": "error", "message": "too many requests", "count": 0}
        assert source.error_count == 1
        assert source.last_error == "too many requests"
        assert source.metadata_["last_fetch_outcome"]["code"] == "http_429"
        assert source.metadata_["last_fetch_outcome"]["severity"] == "error"
        assert source.metadata_["fetch_failure"]["last_code"] == "http_429"
        assert source.metadata_["fetch_failure"]["severity"] == "error"
        assert source.metadata_["fetch_failure"]["cooldown_until"]
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_fetch_pipeline_records_fulltext_profile_fields(self):
        from app.domains.fetch.profile import summarize_profile
        from app.domains.fetch.coordinator import run_fetch_pipeline

        source = _make_source(use_keyword_filter=False)
        source.metadata_ = {"rss_url": "https://example.com/feed.xml"}
        db = MagicMock()
        raw_contents = [_raw(external_id="one"), _raw(external_id="two")]

        full_content = MagicMock(spec=Content)
        full_content.id = uuid4()
        full_content.external_id = "one"
        full_content.original_url = "https://example.com/1"
        full_content.full_content = "A" * 300
        full_content.summary = ""
        full_content.metadata_ = {"fulltext_status": "full"}

        partial_content = MagicMock(spec=Content)
        partial_content.id = uuid4()
        partial_content.external_id = "two"
        partial_content.original_url = "https://example.com/2"
        partial_content.full_content = "short"
        partial_content.summary = ""
        partial_content.metadata_ = {"fulltext_status": "partial"}
        from app.domains.ingest.storage import PostprocessCandidate, StorageResult

        storage_result = StorageResult(
            requested_count=2,
            saved_ids=[str(full_content.id), str(partial_content.id)],
            postprocess_candidates=[
                PostprocessCandidate(str(full_content.id), "new_insert", "a" * 64),
                PostprocessCandidate(str(partial_content.id), "new_insert", "b" * 64),
            ],
            latest_saved_marker="one",
        )

        with patch(
            "app.domains.fetch.collector_stage.CollectorStage.execute",
            new=AsyncMock(return_value=(raw_contents, None, None)),
        ), patch(
            "app.domains.ingest.normalizer.NormalizerStage.execute",
            new=AsyncMock(return_value=(raw_contents, 0)),
        ), patch(
            "app.domains.fetch.coordinator.build_raw_content_objects",
            new=AsyncMock(return_value=([full_content, partial_content], 0)),
        ), patch(
            "app.domains.ingest.storage.StorageStage.execute",
            return_value=storage_result,
        ):
            result = await run_fetch_pipeline(db, source, manual_trigger=False)

        assert result["status"] == "success"
        assert result["saved"] == 2
        profile = summarize_profile(source)
        assert profile["fulltext_success_rate_7d"] == 0.5
        assert profile["preferred_strategy"] == "rss"
        db.commit.assert_called_once()

    def test_error_warning_increments_error_count(self):
        from app.domains.fetch.coordinator import _update_source_status

        source = _make_source(error_count=0)
        source.metadata_ = {}
        _update_source_status(source, "msg", ("auth_error", "error", "认证失败"), "ok", "info", "ok")

        assert source.error_count == 1

    def test_non_error_warning_resets_error_count(self):
        from app.domains.fetch.coordinator import _update_source_status

        source = _make_source(error_count=5)
        source.metadata_ = {}
        _update_source_status(source, "msg", ("stale", "warning", "内容过时"), "ok", "info", "ok")

        assert source.error_count == 0
        assert "fetch_failure" not in source.metadata_

    def test_cooldown_warning_records_fetch_failure_without_error_count(self):
        from app.domains.fetch.coordinator import _update_source_status

        source = _make_source(error_count=5)
        source.metadata_ = {}
        _update_source_status(source, "msg", ("http_429", "warning", "请求限流"), "ok", "info", "ok")

        assert source.error_count == 0
        assert source.metadata_["fetch_failure"]["last_code"] == "http_429"
        assert source.metadata_["fetch_failure"]["severity"] == "warning"
        assert source.metadata_["fetch_failure"]["cooldown_until"]

    def test_no_warning_resets_error_count(self):
        from app.domains.fetch.coordinator import _update_source_status

        source = _make_source(error_count=3)
        source.metadata_ = {}
        _update_source_status(source, None, None, "ok", "info", "抓取成功")

        assert source.error_count == 0


# ===========================================================================
# dedupe — handle_external_id_duplicate
# ===========================================================================

class TestHandleExternalIdDuplicate:

    def test_no_existing_returns_false(self):
        from app.domains.ingest.dedupe import handle_external_id_duplicate

        db = MagicMock()
        source = _make_source()

        query_chain = db.query.return_value
        query_chain.filter.return_value.first.return_value = None
        query_chain.join.return_value.filter.return_value.first.return_value = None

        result = handle_external_id_duplicate(db, source, _raw(), "ext-1")

        assert result is False

    def test_same_source_duplicate_returns_true(self):
        from app.domains.ingest.dedupe import handle_external_id_duplicate

        db = MagicMock()
        source = _make_source()

        existing = MagicMock(spec=Content)
        existing.metadata_ = {}
        existing.full_content = None
        existing.summary = None
        existing.title = "Old Title"

        first_query = MagicMock()
        first_query.filter.return_value.first.return_value = existing

        cross_query = MagicMock()
        cross_query.filter.return_value.first.return_value = None

        db.query.side_effect = [first_query, cross_query]

        result = handle_external_id_duplicate(db, source, _raw(), "ext-1")

        assert result is True
        # The helper must NOT commit — that's the coordinator's job at the
        # batch boundary (see dedupe docstring / Phase 2 P1).
        db.commit.assert_not_called()

    def test_duplicate_detected_by_original_url_when_external_id_differs(self):
        from app.domains.ingest.dedupe import handle_external_id_duplicate

        db = MagicMock()
        source = _make_source()
        slug = (
            "https://www.theverge.com/ai-artificial-intelligence/934521/"
            "google-synthid-c2pa-content-credentials-ai-labelling-efforts"
        )

        existing = MagicMock(spec=Content)
        existing.metadata_ = {}
        existing.full_content = "existing body"
        existing.summary = "summary"
        existing.title = "Old Title"
        existing.is_user_edited = False

        first_query = MagicMock()
        first_query.filter.return_value.first.return_value = existing
        cross_query = MagicMock()
        cross_query.filter.return_value.first.return_value = None
        db.query.side_effect = [first_query, cross_query]

        raw = _raw(url=slug)
        result = handle_external_id_duplicate(
            db,
            source,
            raw,
            "https://www.theverge.com/?p=934521",
        )

        assert result is True

    def test_duplicate_detected_by_canonical_external_id(self):
        from app.domains.ingest.dedupe import handle_external_id_duplicate

        db = _build_sync_db_session()
        source = Source(name="Canonical Source", type=SourceType.WEBSITE, url="https://example.com")
        db.add(source)
        db.flush()
        existing = Content(
            source_id=source.id,
            external_id="old-feed-guid",
            title="Existing",
            original_url="https://example.com/amp/story",
            content_type="website",
            full_content="existing body",
            metadata_={"canonical_external_id": "https://example.com/news/story"},
        )
        db.add(existing)
        db.commit()

        raw = _raw(
            url="https://example.com/mobile/story",
            external_id="new-feed-guid",
            metadata={
                "canonical_url": "https://example.com/news/story",
                "canonical_external_id": "https://example.com/news/story",
            },
        )

        try:
            assert handle_external_id_duplicate(db, source, raw, "new-feed-guid") is True
        finally:
            bind = db.get_bind()
            db.close()
            bind.dispose()

    def test_cross_source_sets_metadata(self):
        from app.domains.ingest.dedupe import handle_external_id_duplicate

        db = MagicMock()
        source = _make_source()

        first_query = MagicMock()
        first_query.filter.return_value.first.return_value = None

        cross_match = MagicMock()
        cross_match.__getitem__ = MagicMock(return_value="cross-id")

        second_query = MagicMock()
        second_query.filter.return_value.first.return_value = cross_match

        db.query.side_effect = [first_query, second_query]

        raw = _raw()
        result = handle_external_id_duplicate(db, source, raw, "ext-1")

        assert result is False
        assert "cross_source_external_id_match" in raw.get("metadata", {})

    def test_backfill_fulltext_for_duplicate(self):
        from app.domains.ingest.dedupe import handle_external_id_duplicate

        db = MagicMock()
        source = _make_source()

        existing = MagicMock(spec=Content)
        existing.metadata_ = {}
        existing.full_content = None
        existing.summary = None
        existing.is_user_edited = False
        existing.title = "http://old-url"

        first_query = MagicMock()
        first_query.filter.return_value.first.return_value = existing

        cross_query = MagicMock()
        cross_query.filter.return_value.first.return_value = None

        db.query.side_effect = [first_query, cross_query]

        long_text = "A" * 400
        raw = _raw(content=long_text, metadata={"article_fulltext": True})
        result = handle_external_id_duplicate(db, source, raw, "ext-1")

        assert result is True
        assert existing.full_content is not None

    def test_skips_backfill_if_edited(self):
        from app.domains.ingest.dedupe import handle_external_id_duplicate

        db = MagicMock()
        source = _make_source()

        existing = MagicMock(spec=Content)
        existing.metadata_ = {}
        existing.full_content = "User manual text"
        existing.is_user_edited = True

        first_query = MagicMock()
        first_query.filter.return_value.first.return_value = existing
        db.query.side_effect = [first_query, MagicMock()]

        raw = _raw(content="Better scraped text", metadata={"article_fulltext": True})
        result = handle_external_id_duplicate(db, source, raw, "ext-1")

        assert result is True
        # Should NOT have updated to "Better scraped text"
        assert existing.full_content == "User manual text"

    def test_dedupe_batch_issues_no_per_row_commits(self):
        """Regression guard for Phase 2 P1: N duplicate rows must not fsync N times."""
        from app.domains.ingest.dedupe import handle_external_id_duplicate

        db = MagicMock()
        source = _make_source()

        def _fresh_queries():
            existing = MagicMock(spec=Content)
            existing.metadata_ = {}
            existing.full_content = None
            existing.summary = None
            existing.is_user_edited = False
            existing.title = "Old"
            same_q = MagicMock()
            same_q.filter.return_value.first.return_value = existing
            cross_q = MagicMock()
            cross_q.filter.return_value.first.return_value = None
            return [same_q, cross_q]

        queries: list[MagicMock] = []
        for _ in range(5):
            queries.extend(_fresh_queries())
        db.query.side_effect = queries

        for i in range(5):
            assert handle_external_id_duplicate(db, source, _raw(), f"ext-{i}") is True

        db.commit.assert_not_called()


# ===========================================================================
# NormalizerStage — hydrated-HTML preprocessing (backfill for existing stubs)
# ===========================================================================


class TestNormalizerStageDiagnostics:

    @pytest.mark.asyncio
    async def test_non_feed_freshness_window_scales_with_fetch_interval(self):
        from app.domains.ingest.normalizer import NormalizerStage

        db = _build_sync_db_session()
        try:
            source = Source(
                name="X Feed",
                type=SourceType.X,
                url="https://x.com/example",
                fetch_interval=120,
            )
            db.add(source)
            db.flush()

            diagnostics = []
            valid, stale_skipped = await NormalizerStage.execute(
                db,
                source,
                [
                    {
                        "title": "Recent enough tweet",
                        "url": "https://x.com/example/status/1",
                        "external_id": "x-1",
                        "content": "body text",
                        "publish_time": (datetime.now() - timedelta(minutes=180)).isoformat(),
                    }
                ],
                manual_trigger=False,
                diagnostics=diagnostics,
            )

            assert len(valid) == 1
            assert stale_skipped == 0
            assert diagnostics == []
        finally:
            bind = db.get_bind()
            db.close()
            bind.dispose()

    @pytest.mark.asyncio
    async def test_duplicate_external_id_records_skip_diagnostic(self):
        from app.domains.ingest.normalizer import NormalizerStage

        db = _build_sync_db_session()
        try:
            source = Source(name="Feed", type=SourceType.RSS, url="https://example.com/feed.xml")
            db.add(source)
            db.flush()
            db.add(
                Content(
                    source_id=source.id,
                    external_id="https://example.com/story",
                    title="Existing Story",
                    original_url="https://example.com/story",
                    content_type="rss",
                    full_content="Existing body",
                    publish_time=datetime.now(),
                )
            )
            db.flush()

            diagnostics = []
            valid, stale_skipped = await NormalizerStage.execute(
                db,
                source,
                [
                    {
                        "title": "Existing Story",
                        "url": "https://example.com/story",
                        "external_id": "https://example.com/story",
                        "content": "body text",
                        "publish_time": datetime.now().isoformat(),
                    }
                ],
                manual_trigger=True,
                diagnostics=diagnostics,
            )

            assert valid == []
            assert stale_skipped == 0
            assert diagnostics == [
                {
                    "reason": "duplicate_external_id",
                    "detail": "https://example.com/story",
                    "title": "Existing Story",
                    "url": "https://example.com/story",
                }
            ]
        finally:
            bind = db.get_bind()
            db.close()
            bind.dispose()


class TestMaterializeHydratedFulltext:
    """Guards the fix for: paywall re-fetches failing to backfill existing
    stub rows because ``_hydrate_direct_articles`` put HTML in ``raw_content["html"]``
    but left ``content`` empty, which caused ``handle_external_id_duplicate``
    to skip the upgrade path. See :func:`_materialize_hydrated_fulltext`.
    """

    @pytest.mark.asyncio
    async def test_html_with_empty_content_gets_extracted_and_marked(self):
        from app.domains.ingest.normalizer import _materialize_hydrated_fulltext

        raw_content = {
            "url": "https://example.com/article",
            "content": "",
            "html": "<html><body><article>" + ("Real article body. " * 40) + "</article></body></html>",
            "metadata": {},
        }

        async def _fake_extract(html, url):  # noqa: ARG001 - signature mirrors real extractor
            return "Real article body. " * 40

        with patch("app.domains.ingest.extractor.ContentExtractor") as MockExtractor:
            MockExtractor.return_value.extract = _fake_extract
            await _materialize_hydrated_fulltext(raw_content)

        assert len(raw_content["content"]) >= 280
        assert raw_content["metadata"]["article_fulltext"] is True

    @pytest.mark.asyncio
    async def test_structured_html_is_used_before_generic_extractor(self):
        from app.domains.ingest.normalizer import _materialize_hydrated_fulltext

        body = "Structured article body from JSON-LD. " * 12
        raw_content = {
            "url": "https://example.com/article",
            "content": "",
            "html": (
                '<html><head><script type="application/ld+json">'
                f'{{"@type": "NewsArticle", "articleBody": "{body}"}}'
                "</script></head><body><p>Subscribe</p></body></html>"
            ),
            "metadata": {},
        }

        with patch("app.domains.ingest.extractor.ContentExtractor") as MockExtractor:
            await _materialize_hydrated_fulltext(raw_content)
            MockExtractor.assert_not_called()

        assert raw_content["content"].startswith("Structured article body")
        assert raw_content["metadata"]["article_fulltext"] is True
        assert raw_content["metadata"]["article_extract_method"] == "structured:json_ld"

    @pytest.mark.asyncio
    async def test_hydrated_html_stamps_canonical_and_publish_time_metadata(self):
        from app.domains.ingest.normalizer import _materialize_hydrated_fulltext

        body = "Structured article body from JSON-LD. " * 12
        raw_content = {
            "url": "https://example.com/amp/story",
            "content": "",
            "html": (
                '<html><head><script type="application/ld+json">'
                + json.dumps(
                    {
                        "@type": "NewsArticle",
                        "url": "https://example.com/news/story",
                        "datePublished": "2026-07-02T01:02:03Z",
                        "articleBody": body,
                    }
                )
                + "</script></head><body><p>Subscribe</p></body></html>"
            ),
            "metadata": {"publish_time_estimated": True},
            "publish_time": None,
        }

        await _materialize_hydrated_fulltext(raw_content)

        assert raw_content["metadata"]["canonical_url"] == "https://example.com/news/story"
        assert raw_content["metadata"]["canonical_external_id"] == "https://example.com/news/story"
        assert raw_content["metadata"]["publish_time_source"] == "html_metadata"
        assert raw_content["publish_time"].year == 2026
        assert raw_content["content"].startswith("Structured article body")

    @pytest.mark.asyncio
    async def test_flat_structured_html_falls_back_to_generic_extractor(self):
        from app.domains.ingest.normalizer import _materialize_hydrated_fulltext

        flat_body = "虎嗅结构化正文没有段落边界但长度很长。" * 180
        fallback_body = "\n\n".join(
            f"第{i}段真实正文，来自 DOM 提取路径，保留了段落结构，并包含足够的正文细节用于通过全文长度阈值。"
            for i in range(1, 8)
        )
        raw_content = {
            "url": "https://example.com/article",
            "content": "",
            "html": (
                '<html><head><script type="application/ld+json">'
                f'{{"@type": "NewsArticle", "articleBody": {json.dumps(flat_body, ensure_ascii=False)}}}'
                "</script></head><body><article>"
                + "".join(f"<p>第{i}段真实正文。</p>" for i in range(1, 8))
                + "</article></body></html>"
            ),
            "metadata": {},
        }

        with patch("app.domains.ingest.extractor.ContentExtractor") as MockExtractor:
            MockExtractor.return_value.extract = AsyncMock(return_value=fallback_body)
            await _materialize_hydrated_fulltext(raw_content)

        assert raw_content["content"] == fallback_body
        assert raw_content["metadata"]["article_fulltext"] is True
        assert raw_content["metadata"]["article_extract_method"] == "content_extractor"

    @pytest.mark.asyncio
    async def test_noop_when_no_html(self):
        from app.domains.ingest.normalizer import _materialize_hydrated_fulltext

        raw_content = {"url": "https://example.com/x", "content": "short snippet"}
        await _materialize_hydrated_fulltext(raw_content)

        assert raw_content["content"] == "short snippet"
        assert "article_fulltext" not in raw_content.get("metadata", {})

    @pytest.mark.asyncio
    async def test_noop_when_content_already_populated(self):
        """Avoid re-extracting when the collector already gave us long fulltext
        (e.g., RSS feeds that include the whole article body inline)."""
        from app.domains.ingest.normalizer import _materialize_hydrated_fulltext

        populated = "X" * 400
        raw_content = {
            "url": "https://example.com/article",
            "content": populated,
            "html": "<html>...</html>",
            "metadata": {},
        }

        with patch("app.domains.ingest.extractor.ContentExtractor") as MockExtractor:
            await _materialize_hydrated_fulltext(raw_content)
            MockExtractor.assert_not_called()

        assert raw_content["content"] == populated

    @pytest.mark.asyncio
    async def test_extracted_text_below_threshold_is_discarded(self):
        """If the page is still a paywall shell / signup prompt, we must not
        mark it as fulltext — that would clobber legitimate existing stubs
        with garbage."""
        from app.domains.ingest.normalizer import _materialize_hydrated_fulltext

        raw_content = {
            "url": "https://paywall.test/x",
            "content": "",
            "html": "<html><body><p>Subscribe to continue</p></body></html>",
            "metadata": {},
        }

        async def _tiny_extract(html, url):  # noqa: ARG001
            return "Subscribe to continue"

        with patch("app.domains.ingest.extractor.ContentExtractor") as MockExtractor:
            MockExtractor.return_value.extract = _tiny_extract
            await _materialize_hydrated_fulltext(raw_content)

        assert raw_content["content"] == ""
        assert "article_fulltext" not in raw_content["metadata"]


# ===========================================================================
# canonical dedupe / external id helpers
# ===========================================================================

class TestPipelineUtils:

    def test_dedupe_raw_contents_removes_duplicates(self):
        from app.domains.fetch.collector_stage import dedupe_raw_contents

        items = [
            {"external_id": "a", "url": "u1", "title": "T1"},
            {"external_id": "a", "url": "u2", "title": "T2"},
            {"external_id": "b", "url": "u3", "title": "T3"},
        ]
        result = dedupe_raw_contents(items)
        assert len(result) == 2

    def test_dedupe_fallback_to_url(self):
        from app.domains.fetch.collector_stage import dedupe_raw_contents

        items = [
            {"url": "https://x.com/1", "title": "A"},
            {"url": "https://x.com/1", "title": "B"},
        ]
        result = dedupe_raw_contents(items)
        assert len(result) == 1

    def test_dedupe_raw_contents_merges_wordpress_p_and_slug_urls(self):
        from app.domains.fetch.collector_stage import dedupe_raw_contents

        slug = (
            "https://www.theverge.com/ai-artificial-intelligence/934521/"
            "google-synthid-c2pa-content-credentials-ai-labelling-efforts"
        )
        items = [
            {"external_id": "https://www.theverge.com/?p=934521", "url": slug, "title": "A"},
            {"external_id": slug, "url": slug, "title": "B"},
        ]
        result = dedupe_raw_contents(items)
        assert len(result) == 1

    def test_normalize_external_id_canonicalizes_article_urls(self):
        from app.utils.url import normalize_external_id

        assert normalize_external_id("https://www.theverge.com/?p=934521") == (
            "https://theverge.com/article:934521"
        )

    def test_normalize_external_id_short(self):
        from app.utils.url import normalize_external_id

        assert normalize_external_id("short-id") == "short-id"

    def test_normalize_external_id_long_hashed(self):
        from app.utils.url import normalize_external_id

        long_id = "x" * 300
        result = normalize_external_id(long_id)
        assert result.startswith("hash:")
        assert len(result) <= 255

    def test_normalize_external_id_none(self):
        from app.utils.url import normalize_external_id

        assert normalize_external_id(None) is None


@pytest.mark.asyncio
async def test_web_clean_enabled_persists_markdown_while_quality_uses_plain_text():
    from types import SimpleNamespace

    from app.domains.fetch.web_clean.contracts import CleanResult
    from app.domains.ingest.build_content import build_raw_content_objects

    source = _make_source(type=SourceType.WEBSITE)
    source.metadata_ = {"web_clean_mode": "write"}
    article_text = "Heading\n\nBody paragraph with enough useful context. " * 15
    article_markdown = "## Heading\n\n[Source](https://example.com/source)\n\n```python\nprint('ok')\n```\n\n" + article_text
    clean_result = CleanResult(
        url="https://example.com/story",
        title="Heading",
        author=None,
        published_time=None,
        canonical_url=None,
        site_name=None,
        language=None,
        article_html="<article><h2>Heading</h2></article>",
        article_text=article_text,
        article_markdown=article_markdown,
        clean_full_html=None,
        extraction_method="template_selector",
        template_id="example-v1",
        quality_status="full",
        quality_score=0.9,
        trace={
            "selected_method": "template_selector",
            "candidates": [{"method": "template_selector", "rejected_reason": None}],
        },
        metadata={"quality_signals": {"paragraph_count": 4, "link_density": 0.1}},
    )
    extractor = AsyncMock()
    extractor.extract_clean.return_value = clean_result
    settings = SimpleNamespace(
        pim_web_clean_enabled=True,
        pim_web_clean_shadow=True,
        pim_web_clean_template_enabled=True,
        pim_web_clean_max_html_bytes=3_000_000,
        pim_web_clean_timeout_ms=8_000,
        pim_web_clean_write_metadata=True,
    )
    raw = [_raw(url="https://example.com/story", content="legacy body", html="<article>legacy body</article>")]

    with (
        _no_reject,
        patch("app.domains.ingest.extractor.ContentExtractor", return_value=extractor),
        patch("app.domains.ingest.build_content.get_settings", return_value=settings),
    ):
        results, failures = await build_raw_content_objects(raw, source)

    assert failures == 0
    assert len(results) == 1
    assert results[0].full_content == article_markdown
    assert "[Source](https://example.com/source)" in results[0].full_content
    assert "```python" in results[0].full_content
    assert results[0].summary.startswith("Heading")
    assert results[0].metadata_["web_clean"]["shadow"] is False


@pytest.mark.asyncio
async def test_web_clean_shadow_does_not_replace_legacy_full_content():
    from types import SimpleNamespace

    from app.domains.fetch.web_clean.contracts import CleanResult
    from app.domains.ingest.build_content import build_raw_content_objects

    source = _make_source(type=SourceType.WEBSITE)
    clean_result = CleanResult(
        url="https://example.com/story",
        title=None,
        author=None,
        published_time=None,
        canonical_url=None,
        site_name=None,
        language=None,
        article_html="<article>new candidate</article>",
        article_text="new candidate " * 50,
        article_markdown="## New candidate\n\n" + ("new candidate " * 50),
        clean_full_html=None,
        extraction_method="beautifulsoup",
        template_id=None,
        quality_status="good",
        quality_score=0.8,
        trace={"selected_method": "beautifulsoup", "candidates": []},
        metadata={"quality_signals": {"paragraph_count": 3}},
    )
    extractor = AsyncMock()
    extractor.extract_clean.return_value = clean_result
    settings = SimpleNamespace(
        pim_web_clean_enabled=False,
        pim_web_clean_shadow=True,
        pim_web_clean_template_enabled=False,
        pim_web_clean_max_html_bytes=3_000_000,
        pim_web_clean_timeout_ms=8_000,
        pim_web_clean_write_metadata=True,
    )
    legacy = "legacy production body " * 40
    raw = [_raw(url="https://example.com/story", content=legacy, html="<article>new candidate</article>")]

    with (
        _no_reject,
        patch("app.domains.ingest.extractor.ContentExtractor", return_value=extractor),
        patch("app.domains.ingest.build_content.get_settings", return_value=settings),
    ):
        results, failures = await build_raw_content_objects(raw, source)

    assert failures == 0
    assert results[0].full_content == legacy.strip()
    assert results[0].metadata_["web_clean"]["shadow"] is True
    assert "shadow_diff" in results[0].metadata_["web_clean"]


@pytest.mark.asyncio
async def test_web_clean_shadow_auto_promotes_clear_truncation_repair():
    from types import SimpleNamespace

    from app.domains.fetch.web_clean.contracts import CleanResult
    from app.domains.ingest.build_content import build_raw_content_objects

    source = _make_source(type=SourceType.WEBSITE)
    clean_text = "完整正文段落。" * 300
    clean_result = CleanResult(
        url="https://example.com/story",
        title="Story",
        author=None,
        published_time=None,
        canonical_url="https://example.com/story",
        site_name="Example",
        language="zh",
        article_html="<article>full</article>",
        article_text=clean_text,
        article_markdown=clean_text,
        clean_full_html=None,
        extraction_method="trafilatura",
        template_id=None,
        quality_status="full",
        quality_score=0.93,
        trace={
            "selected_method": "trafilatura",
            "candidates": [{"method": "trafilatura", "rejected_reason": None}],
        },
        metadata={"quality_signals": {"paragraph_count": 20}},
    )
    extractor = AsyncMock()
    extractor.extract_clean.return_value = clean_result
    settings = SimpleNamespace(
        pim_web_clean_enabled=False,
        pim_web_clean_shadow=True,
        pim_web_clean_template_enabled=False,
        pim_web_clean_max_html_bytes=3_000_000,
        pim_web_clean_timeout_ms=8_000,
        pim_web_clean_write_metadata=True,
    )
    legacy = "截断正文。" * 80
    raw = [_raw(url="https://example.com/story", content=legacy, html="<article>partial</article>")]

    with (
        _no_reject,
        patch("app.domains.ingest.extractor.ContentExtractor", return_value=extractor),
        patch("app.domains.ingest.build_content.get_settings", return_value=settings),
    ):
        results, failures = await build_raw_content_objects(raw, source)

    assert failures == 0
    assert results[0].full_content == clean_text
    assert results[0].metadata_["web_clean"]["shadow"] is False
    assert results[0].metadata_["web_clean"]["auto_promoted"] is True


@pytest.mark.asyncio
async def test_web_clean_enabled_rejected_candidate_keeps_legacy_body():
    from types import SimpleNamespace

    from app.domains.fetch.web_clean.contracts import CleanResult
    from app.domains.ingest.build_content import build_raw_content_objects

    source = _make_source(type=SourceType.WEBSITE)
    source.metadata_ = {"web_clean_mode": "write"}
    clean_result = CleanResult(
        url="https://example.com/login",
        title="Login",
        author=None,
        published_time=None,
        canonical_url=None,
        site_name=None,
        language=None,
        article_html="<article>Please sign in</article>",
        article_text="Please sign in to continue " * 20,
        article_markdown="Please sign in to continue " * 20,
        clean_full_html=None,
        extraction_method="beautifulsoup",
        template_id=None,
        quality_status="login_required",
        quality_score=0.1,
        trace={
            "selected_method": "beautifulsoup",
            "candidates": [{"method": "beautifulsoup", "rejected_reason": "login_required"}],
        },
        metadata={"quality_signals": {"paragraph_count": 1}},
    )
    extractor = AsyncMock()
    extractor.extract_clean.return_value = clean_result
    settings = SimpleNamespace(
        pim_web_clean_enabled=True,
        pim_web_clean_shadow=True,
        pim_web_clean_template_enabled=True,
        pim_web_clean_max_html_bytes=3_000_000,
        pim_web_clean_timeout_ms=8_000,
        pim_web_clean_write_metadata=True,
    )
    legacy = "legacy authorized article body " * 40
    raw = [_raw(url="https://example.com/login", content=legacy, html="<article>Please sign in</article>")]

    with (
        _no_reject,
        patch("app.domains.ingest.extractor.ContentExtractor", return_value=extractor),
        patch("app.domains.ingest.build_content.get_settings", return_value=settings),
    ):
        results, failures = await build_raw_content_objects(raw, source)

    assert failures == 0
    assert results[0].full_content == legacy.strip()
    assert results[0].metadata_["web_clean"]["quality_status"] == "login_required"


@pytest.mark.asyncio
async def test_web_clean_global_master_does_not_write_without_source_opt_in():
    from types import SimpleNamespace

    from app.domains.fetch.web_clean.contracts import CleanResult
    from app.domains.ingest.build_content import build_raw_content_objects

    source = _make_source(type=SourceType.WEBSITE)
    clean_result = CleanResult(
        url="https://example.com/story",
        title="New",
        author=None,
        published_time=None,
        canonical_url=None,
        site_name=None,
        language=None,
        article_html="<article>new</article>",
        article_text="new clean body " * 50,
        article_markdown="## New\n\n" + ("new clean body " * 50),
        clean_full_html=None,
        extraction_method="beautifulsoup",
        template_id=None,
        quality_status="good",
        quality_score=0.9,
        trace={"selected_method": "beautifulsoup", "candidates": []},
        metadata={"quality_signals": {"paragraph_count": 3}},
    )
    extractor = AsyncMock()
    extractor.extract_clean.return_value = clean_result
    settings = SimpleNamespace(
        pim_web_clean_enabled=True,
        pim_web_clean_shadow=True,
        pim_web_clean_template_enabled=True,
        pim_web_clean_max_html_bytes=3_000_000,
        pim_web_clean_timeout_ms=8_000,
        pim_web_clean_write_metadata=True,
    )
    legacy = "legacy body remains authoritative " * 40
    raw = [_raw(url="https://example.com/story", content=legacy, html="<article>new</article>")]

    with (
        _no_reject,
        patch("app.domains.ingest.extractor.ContentExtractor", return_value=extractor),
        patch("app.domains.ingest.build_content.get_settings", return_value=settings),
    ):
        results, failures = await build_raw_content_objects(raw, source)

    assert failures == 0
    assert results[0].full_content == legacy.strip()
    assert results[0].metadata_["web_clean"]["shadow"] is True
    assert results[0].metadata_["web_clean"]["source_mode"] == "shadow"
