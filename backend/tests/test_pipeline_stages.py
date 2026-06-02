"""Tests for pipeline stages: CollectorStage, StorageStage, coordinator, dedupe.

Phase 7 retired :mod:`app.pipeline.ai_stage` (the legacy deprecated stage
had no production callers; the tests that pinned it were removed alongside
the implementation).
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

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


# ===========================================================================
# CollectorStage
# ===========================================================================

class TestCollectorStage:

    @pytest.mark.asyncio
    async def test_fetches_from_primary_url(self):
        """CollectorStage should call collector.fetch for the source URL."""
        from app.pipeline.collector_stage import CollectorStage

        source = _make_source(type=SourceType.RSS)
        source.auth_config = None
        source.auth_config_id = None

        mock_collector = MagicMock()
        mock_collector.fetch = AsyncMock(return_value=[_raw()])
        mock_collector.filter_new_content = MagicMock(side_effect=lambda items, _: items)

        db = MagicMock()

        with patch("app.pipeline.collector_stage.get_collector", return_value=mock_collector), \
             patch("app.pipeline.collector_stage.get_source_urls", return_value=["https://example.com"]), \
             patch("app.pipeline.collector_stage.dedupe_raw_contents", side_effect=lambda x: x), \
             patch("app.pipeline.collector_stage.auth_warning_entry", return_value=None), \
             patch("app.pipeline.collector_stage.cookie_hydration_warning_entry", return_value=None), \
             patch("app.pipeline.collector_stage.merge_warning_messages", return_value=None):

            raw, warning, primary = await CollectorStage.execute(db, source)

        assert len(raw) == 1
        mock_collector.fetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_fetch_error_gracefully(self):
        """All URLs failing must surface a fetch_failed error, not silent success."""
        from app.pipeline.collector_stage import CollectorStage

        source = _make_source(type=SourceType.RSS)
        source.auth_config = None
        source.auth_config_id = None

        mock_collector = MagicMock()
        mock_collector.fetch = AsyncMock(side_effect=RuntimeError("network"))

        db = MagicMock()

        with patch("app.pipeline.collector_stage.get_collector", return_value=mock_collector), \
             patch("app.pipeline.collector_stage.get_source_urls", return_value=["https://example.com"]), \
             patch("app.pipeline.collector_stage.dedupe_raw_contents", side_effect=lambda x: x), \
             patch("app.pipeline.collector_stage.auth_warning_entry", return_value=None), \
             patch("app.pipeline.collector_stage.cookie_hydration_warning_entry", return_value=None), \
             patch("app.pipeline.collector_stage.merge_warning_messages", side_effect=lambda *a: next((m for m in a if m), None)):

            raw, warning, primary = await CollectorStage.execute(db, source)

        assert raw == []
        assert primary is not None
        # A bare RuntimeError can't be classified further -> unified "unknown".
        assert primary[0] == "unknown"
        assert primary[1] == "error"

    @pytest.mark.asyncio
    async def test_fetch_failure_is_classified_with_structured_code(self):
        """A classifiable fetch exception surfaces its taxonomy code, not 'fetch_failed'."""
        from app.pipeline.collector_stage import CollectorStage

        source = _make_source(type=SourceType.RSS)
        source.auth_config = None
        source.auth_config_id = None

        mock_collector = MagicMock()
        mock_collector.fetch = AsyncMock(
            side_effect=ValueError("private address is not allowed: 10.0.0.1")
        )

        db = MagicMock()

        with patch("app.pipeline.collector_stage.get_collector", return_value=mock_collector), \
             patch("app.pipeline.collector_stage.get_source_urls", return_value=["https://example.com"]), \
             patch("app.pipeline.collector_stage.dedupe_raw_contents", side_effect=lambda x: x), \
             patch("app.pipeline.collector_stage.auth_warning_entry", return_value=None), \
             patch("app.pipeline.collector_stage.cookie_hydration_warning_entry", return_value=None), \
             patch("app.pipeline.collector_stage.merge_warning_messages", side_effect=lambda *a: next((m for m in a if m), None)):

            raw, warning, primary = await CollectorStage.execute(db, source)

        assert raw == []
        assert primary is not None
        assert primary[0] == "ssrf_blocked"
        assert primary[1] == "error"

    @pytest.mark.asyncio
    async def test_partial_fetch_failure_is_not_flagged_as_error(self):
        """One URL failing while another succeeds must not be flagged fetch_failed."""
        from app.pipeline.collector_stage import CollectorStage

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

        with patch("app.pipeline.collector_stage.get_collector", return_value=mock_collector), \
             patch("app.pipeline.collector_stage.get_source_urls", return_value=["https://bad.com", "https://ok.com"]), \
             patch("app.pipeline.collector_stage.dedupe_raw_contents", side_effect=lambda x: x), \
             patch("app.pipeline.collector_stage.auth_warning_entry", return_value=None), \
             patch("app.pipeline.collector_stage.cookie_hydration_warning_entry", return_value=None), \
             patch("app.pipeline.collector_stage.merge_warning_messages", side_effect=lambda *a: next((m for m in a if m), None)):

            raw, warning, primary = await CollectorStage.execute(db, source)

        assert len(raw) == 1
        assert primary is None

    @pytest.mark.asyncio
    async def test_multiple_urls_concatenated(self):
        """CollectorStage should fetch from multiple source URLs and combine results."""
        from app.pipeline.collector_stage import CollectorStage

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

        with patch("app.pipeline.collector_stage.get_collector", return_value=mock_collector), \
             patch("app.pipeline.collector_stage.get_source_urls", return_value=["https://a.com", "https://b.com"]), \
             patch("app.pipeline.collector_stage.dedupe_raw_contents", side_effect=lambda x: x), \
             patch("app.pipeline.collector_stage.auth_warning_entry", return_value=None), \
             patch("app.pipeline.collector_stage.cookie_hydration_warning_entry", return_value=None), \
             patch("app.pipeline.collector_stage.merge_warning_messages", return_value=None):

            raw, _, _ = await CollectorStage.execute(db, source)

        assert len(raw) == 2
        assert mock_collector.fetch.call_count == 2

    @pytest.mark.asyncio
    async def test_auth_config_auto_bind_for_website(self):
        """When type is website and no auth_config_id, it should try to auto-bind."""
        from app.pipeline.collector_stage import CollectorStage

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

        with patch("app.pipeline.collector_stage.get_collector", return_value=mock_collector), \
             patch("app.pipeline.collector_stage.get_source_urls", return_value=["https://example.com/page"]), \
             patch("app.pipeline.collector_stage.dedupe_raw_contents", side_effect=lambda x: x), \
             patch("app.pipeline.collector_stage.auth_warning_entry", return_value=None), \
             patch("app.pipeline.collector_stage.cookie_hydration_warning_entry", return_value=None), \
             patch("app.pipeline.collector_stage.merge_warning_messages", return_value=None), \
             patch("app.pipeline.collector_stage.url_utils") as mock_url:

            mock_url.normalize_host.return_value = "example.com"
            raw, _, _ = await CollectorStage.execute(db, source)

        db.query.assert_called()

    @pytest.mark.asyncio
    async def test_active_browser_session_skips_password_auto_login(self):
        """An active browser_session's on-disk profile already holds valid cookies;
        running password auto-login anyway (WSJ et al.) only yields false-positive
        ``auth_captcha`` warnings. Verify the stage short-circuits it."""
        from app.pipeline.collector_stage import CollectorStage

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

        with patch("app.pipeline.collector_stage.get_collector", return_value=mock_collector), \
             patch("app.pipeline.collector_stage.get_source_urls", return_value=["https://example.com/x"]), \
             patch("app.pipeline.collector_stage.dedupe_raw_contents", side_effect=lambda x: x), \
             patch("app.pipeline.collector_stage.auth_warning_entry", return_value=None), \
             patch("app.pipeline.collector_stage.cookie_hydration_warning_entry", return_value=None), \
             patch("app.pipeline.collector_stage.merge_warning_messages", return_value=None), \
             patch("app.pipeline.collector_stage.try_parse_auth_credentials", return_value={"username": "u", "password": "p"}), \
             patch("app.pipeline.collector_stage.maybe_refresh_auth_cookies", refresh_mock), \
             patch(
                 "app.pipeline.collector_stage.build_browser_session_runtime",
                 return_value=browser_session_stub,
             ):

            await CollectorStage.execute(db, source)

        refresh_mock.assert_not_awaited()
        runtime_auth = getattr(source, "_runtime_auth")
        assert runtime_auth["browser_session"] == browser_session_stub

    @pytest.mark.asyncio
    async def test_active_but_unvalidated_browser_session_still_runs_auto_login(self):
        """ACTIVE only means a profile exists; without a recent successful
        validation, password auth should still be allowed to refresh cookies."""
        from app.pipeline.collector_stage import CollectorStage

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

        with patch("app.pipeline.collector_stage.get_collector", return_value=mock_collector), \
             patch("app.pipeline.collector_stage.get_source_urls", return_value=["https://example.com/x"]), \
             patch("app.pipeline.collector_stage.dedupe_raw_contents", side_effect=lambda x: x), \
             patch("app.pipeline.collector_stage.auth_warning_entry", return_value=None), \
             patch("app.pipeline.collector_stage.cookie_hydration_warning_entry", return_value=None), \
             patch("app.pipeline.collector_stage.merge_warning_messages", return_value=None), \
             patch("app.pipeline.collector_stage.try_parse_auth_credentials", return_value={"username": "u", "password": "p"}), \
             patch("app.pipeline.collector_stage.maybe_refresh_auth_cookies", refresh_mock), \
             patch(
                 "app.pipeline.collector_stage.build_browser_session_runtime",
                 return_value=browser_session_stub,
             ):

            await CollectorStage.execute(db, source)

        refresh_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_inactive_browser_session_still_runs_auto_login(self):
        """If the browser session is not active (needs_login / error), we should
        fall back to the password auto-login path so the user still gets a chance
        at credential-based cookies."""
        from app.pipeline.collector_stage import CollectorStage

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

        with patch("app.pipeline.collector_stage.get_collector", return_value=mock_collector), \
             patch("app.pipeline.collector_stage.get_source_urls", return_value=["https://example.com/x"]), \
             patch("app.pipeline.collector_stage.dedupe_raw_contents", side_effect=lambda x: x), \
             patch("app.pipeline.collector_stage.auth_warning_entry", return_value=None), \
             patch("app.pipeline.collector_stage.cookie_hydration_warning_entry", return_value=None), \
             patch("app.pipeline.collector_stage.merge_warning_messages", return_value=None), \
             patch("app.pipeline.collector_stage.try_parse_auth_credentials", return_value={"username": "u", "password": "p"}), \
             patch("app.pipeline.collector_stage.maybe_refresh_auth_cookies", refresh_mock), \
             patch(
                 "app.pipeline.collector_stage.build_browser_session_runtime",
                 return_value=browser_session_stub,
             ):

            await CollectorStage.execute(db, source)

        refresh_mock.assert_awaited_once()


# ===========================================================================
# StorageStage
# ===========================================================================

class TestStorageStage:

    def test_saves_contents_and_returns_count(self):
        from app.pipeline.storage_stage import StorageStage

        c1 = MagicMock(spec=Content)
        c1.external_id = "ext-1"
        c1.original_url = "https://example.com/1"
        c2 = MagicMock(spec=Content)
        c2.external_id = "ext-2"
        c2.original_url = "https://example.com/2"

        db = MagicMock()
        nested_ctx = MagicMock()
        db.begin_nested.return_value = nested_ctx
        nested_ctx.__enter__ = MagicMock(return_value=nested_ctx)
        nested_ctx.__exit__ = MagicMock(return_value=False)

        with patch("app.domains.ingest.storage.normalize_external_id", side_effect=lambda x: x):
            saved, marker = StorageStage.execute(db, [c1, c2])

        assert saved == 2
        assert db.add.call_count == 2

    def test_skips_integrity_error(self):
        from sqlalchemy.exc import IntegrityError
        from app.pipeline.storage_stage import StorageStage

        c1 = MagicMock(spec=Content)
        c1.external_id = "dup"
        c1.original_url = "https://example.com/dup"

        db = MagicMock()
        nested_ctx = MagicMock()
        db.begin_nested.return_value = nested_ctx
        nested_ctx.__enter__ = MagicMock(return_value=nested_ctx)
        nested_ctx.__exit__ = MagicMock(return_value=False)
        db.add.side_effect = IntegrityError("dup", {}, None)

        with patch("app.domains.ingest.storage.normalize_external_id", side_effect=lambda x: x):
            saved, marker = StorageStage.execute(db, [c1])

        assert saved == 0

    def test_empty_contents_returns_zero(self):
        from app.pipeline.storage_stage import StorageStage

        db = MagicMock()
        saved, marker = StorageStage.execute(db, [])

        assert saved == 0
        assert marker is None

    def test_marker_from_first_saved(self):
        from app.pipeline.storage_stage import StorageStage

        c1 = MagicMock(spec=Content)
        c1.external_id = "first-id"
        c1.original_url = "https://example.com/1"

        db = MagicMock()
        nested_ctx = MagicMock()
        db.begin_nested.return_value = nested_ctx
        nested_ctx.__enter__ = MagicMock(return_value=nested_ctx)
        nested_ctx.__exit__ = MagicMock(return_value=False)

        with patch("app.domains.ingest.storage.normalize_external_id", return_value="first-id"):
            saved, marker = StorageStage.execute(db, [c1])

        assert saved == 1
        assert marker == "first-id"


# ===========================================================================
# domains.ingest.build_content.build_raw_content_objects
# (Phase 3 step 3 moved this here; Phase 7 retired the
# ``app.pipeline.coordinator._build_raw_content_objects`` alias.)
# ===========================================================================

_no_reject = patch("app.domains.ingest.build_content.get_website_content_reject_reason", return_value=None)


class TestBuildRawContentObjects:

    @pytest.mark.asyncio
    async def test_basic_content_creation(self):
        from app.domains.ingest.build_content import build_raw_content_objects

        source = _make_source()
        raw = [_raw(title="Hello World", content="Some body text")]

        with _no_reject, patch("app.processors.extractor.ContentExtractor") as MockExt:
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

        with _no_reject, patch("app.processors.extractor.ContentExtractor", return_value=mock_extractor):
            results, _build_failures = await build_raw_content_objects(raw, source)

        assert len(results) == 1
        mock_extractor.extract.assert_called_once()

    @pytest.mark.asyncio
    async def test_publish_time_iso_parsing(self):
        from app.domains.ingest.build_content import build_raw_content_objects

        source = _make_source()
        raw = [_raw(publish_time="2025-06-15T10:00:00Z")]

        with _no_reject, patch("app.processors.extractor.ContentExtractor") as MockExt:
            MockExt.return_value = AsyncMock()
            results, _build_failures = await build_raw_content_objects(raw, source)

        assert results[0].publish_time.year == 2025
        assert results[0].publish_time.month == 6

    @pytest.mark.asyncio
    async def test_missing_publish_time_stays_null(self):
        from app.domains.ingest.build_content import build_raw_content_objects

        source = _make_source()
        raw = [_raw(publish_time=None)]

        with _no_reject, patch("app.processors.extractor.ContentExtractor") as MockExt:
            MockExt.return_value = AsyncMock()
            results, _build_failures = await build_raw_content_objects(raw, source)

        assert results[0].publish_time is None

    @pytest.mark.asyncio
    async def test_skips_items_on_error(self):
        from app.domains.ingest.build_content import build_raw_content_objects

        source = _make_source()
        raw = [_raw(), {"title": None}]

        with _no_reject, patch("app.processors.extractor.ContentExtractor") as MockExt:
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

        with _no_reject, patch("app.processors.extractor.ContentExtractor") as MockExt:
            MockExt.return_value = AsyncMock()
            results, _build_failures = await build_raw_content_objects(raw, source)

        assert results[0].summary is not None
        assert results[0].summary.endswith("…")

    @pytest.mark.asyncio
    async def test_metadata_normalised_to_dict_and_quality_stamped(self):
        from app.domains.ingest.build_content import build_raw_content_objects

        source = _make_source()
        raw = [_raw(metadata="not-a-dict")]

        with _no_reject, patch("app.processors.extractor.ContentExtractor") as MockExt:
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

    def test_error_warning_increments_error_count(self):
        from app.pipeline.coordinator import _update_source_status

        source = _make_source(error_count=0)
        source.metadata_ = {}
        _update_source_status(source, "msg", ("auth_error", "error", "认证失败"), "ok", "info", "ok")

        assert source.error_count == 1

    def test_non_error_warning_resets_error_count(self):
        from app.pipeline.coordinator import _update_source_status

        source = _make_source(error_count=5)
        source.metadata_ = {}
        _update_source_status(source, "msg", ("stale", "warning", "内容过时"), "ok", "info", "ok")

        assert source.error_count == 0
        assert "fetch_failure" not in source.metadata_

    def test_cooldown_warning_records_fetch_failure_without_error_count(self):
        from app.pipeline.coordinator import _update_source_status

        source = _make_source(error_count=5)
        source.metadata_ = {}
        _update_source_status(source, "msg", ("http_429", "warning", "请求限流"), "ok", "info", "ok")

        assert source.error_count == 0
        assert source.metadata_["fetch_failure"]["last_code"] == "http_429"
        assert source.metadata_["fetch_failure"]["severity"] == "warning"
        assert source.metadata_["fetch_failure"]["cooldown_until"]

    def test_no_warning_resets_error_count(self):
        from app.pipeline.coordinator import _update_source_status

        source = _make_source(error_count=3)
        source.metadata_ = {}
        _update_source_status(source, None, None, "ok", "info", "抓取成功")

        assert source.error_count == 0


# ===========================================================================
# dedupe — handle_external_id_duplicate
# ===========================================================================

class TestHandleExternalIdDuplicate:

    def test_no_existing_returns_false(self):
        from app.pipeline.dedupe import handle_external_id_duplicate

        db = MagicMock()
        source = _make_source()

        query_chain = db.query.return_value
        query_chain.filter.return_value.first.return_value = None
        query_chain.join.return_value.filter.return_value.first.return_value = None

        result = handle_external_id_duplicate(db, source, _raw(), "ext-1")

        assert result is False

    def test_same_source_duplicate_returns_true(self):
        from app.pipeline.dedupe import handle_external_id_duplicate

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
        from app.pipeline.dedupe import handle_external_id_duplicate

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

    def test_cross_source_sets_metadata(self):
        from app.pipeline.dedupe import handle_external_id_duplicate

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
        from app.pipeline.dedupe import handle_external_id_duplicate

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
        from app.pipeline.dedupe import handle_external_id_duplicate

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
        from app.pipeline.dedupe import handle_external_id_duplicate

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

class TestMaterializeHydratedFulltext:
    """Guards the fix for: paywall re-fetches failing to backfill existing
    stub rows because ``_hydrate_direct_articles`` put HTML in ``raw_content["html"]``
    but left ``content`` empty, which caused ``handle_external_id_duplicate``
    to skip the upgrade path. See :func:`_materialize_hydrated_fulltext`.
    """

    @pytest.mark.asyncio
    async def test_html_with_empty_content_gets_extracted_and_marked(self):
        from app.pipeline.normalizer_stage import _materialize_hydrated_fulltext

        raw_content = {
            "url": "https://example.com/article",
            "content": "",
            "html": "<html><body><article>" + ("Real article body. " * 40) + "</article></body></html>",
            "metadata": {},
        }

        async def _fake_extract(html, url):  # noqa: ARG001 - signature mirrors real extractor
            return "Real article body. " * 40

        with patch("app.processors.extractor.ContentExtractor") as MockExtractor:
            MockExtractor.return_value.extract = _fake_extract
            await _materialize_hydrated_fulltext(raw_content)

        assert len(raw_content["content"]) >= 280
        assert raw_content["metadata"]["article_fulltext"] is True

    @pytest.mark.asyncio
    async def test_structured_html_is_used_before_generic_extractor(self):
        from app.pipeline.normalizer_stage import _materialize_hydrated_fulltext

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

        with patch("app.processors.extractor.ContentExtractor") as MockExtractor:
            await _materialize_hydrated_fulltext(raw_content)
            MockExtractor.assert_not_called()

        assert raw_content["content"].startswith("Structured article body")
        assert raw_content["metadata"]["article_fulltext"] is True
        assert raw_content["metadata"]["article_extract_method"] == "structured:json_ld"

    @pytest.mark.asyncio
    async def test_noop_when_no_html(self):
        from app.pipeline.normalizer_stage import _materialize_hydrated_fulltext

        raw_content = {"url": "https://example.com/x", "content": "short snippet"}
        await _materialize_hydrated_fulltext(raw_content)

        assert raw_content["content"] == "short snippet"
        assert "article_fulltext" not in raw_content.get("metadata", {})

    @pytest.mark.asyncio
    async def test_noop_when_content_already_populated(self):
        """Avoid re-extracting when the collector already gave us long fulltext
        (e.g., RSS feeds that include the whole article body inline)."""
        from app.pipeline.normalizer_stage import _materialize_hydrated_fulltext

        populated = "X" * 400
        raw_content = {
            "url": "https://example.com/article",
            "content": populated,
            "html": "<html>...</html>",
            "metadata": {},
        }

        with patch("app.processors.extractor.ContentExtractor") as MockExtractor:
            await _materialize_hydrated_fulltext(raw_content)
            MockExtractor.assert_not_called()

        assert raw_content["content"] == populated

    @pytest.mark.asyncio
    async def test_extracted_text_below_threshold_is_discarded(self):
        """If the page is still a paywall shell / signup prompt, we must not
        mark it as fulltext — that would clobber legitimate existing stubs
        with garbage."""
        from app.pipeline.normalizer_stage import _materialize_hydrated_fulltext

        raw_content = {
            "url": "https://paywall.test/x",
            "content": "",
            "html": "<html><body><p>Subscribe to continue</p></body></html>",
            "metadata": {},
        }

        async def _tiny_extract(html, url):  # noqa: ARG001
            return "Subscribe to continue"

        with patch("app.processors.extractor.ContentExtractor") as MockExtractor:
            MockExtractor.return_value.extract = _tiny_extract
            await _materialize_hydrated_fulltext(raw_content)

        assert raw_content["content"] == ""
        assert "article_fulltext" not in raw_content["metadata"]


# ===========================================================================
# pipeline.utils — dedupe_raw_contents & normalize_external_id
# ===========================================================================

class TestPipelineUtils:

    def test_dedupe_raw_contents_removes_duplicates(self):
        from app.pipeline.utils import dedupe_raw_contents

        items = [
            {"external_id": "a", "url": "u1", "title": "T1"},
            {"external_id": "a", "url": "u2", "title": "T2"},
            {"external_id": "b", "url": "u3", "title": "T3"},
        ]
        result = dedupe_raw_contents(items)
        assert len(result) == 2

    def test_dedupe_fallback_to_url(self):
        from app.pipeline.utils import dedupe_raw_contents

        items = [
            {"url": "https://x.com/1", "title": "A"},
            {"url": "https://x.com/1", "title": "B"},
        ]
        result = dedupe_raw_contents(items)
        assert len(result) == 1

    def test_dedupe_raw_contents_merges_wordpress_p_and_slug_urls(self):
        from app.pipeline.utils import dedupe_raw_contents

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
        from app.pipeline.utils import normalize_external_id

        assert normalize_external_id("https://www.theverge.com/?p=934521") == (
            "https://theverge.com/article:934521"
        )

    def test_normalize_external_id_short(self):
        from app.pipeline.utils import normalize_external_id

        assert normalize_external_id("short-id") == "short-id"

    def test_normalize_external_id_long_hashed(self):
        from app.pipeline.utils import normalize_external_id

        long_id = "x" * 300
        result = normalize_external_id(long_id)
        assert result.startswith("hash:")
        assert len(result) <= 255

    def test_normalize_external_id_none(self):
        from app.pipeline.utils import normalize_external_id

        assert normalize_external_id(None) is None
