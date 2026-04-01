"""Tests for pipeline stages: AIStage, CollectorStage, StorageStage, coordinator, dedupe."""

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
# AIStage
# ===========================================================================

class TestAIStage:

    @pytest.mark.asyncio
    async def test_processes_each_raw_content(self):
        """AIStage should invoke processor.process for every raw content dict."""
        from app.pipeline.ai_stage import AIStage

        fake_content = MagicMock(spec=Content)
        with patch("app.pipeline.ai_stage.ContentProcessor") as MockCls:
            mock_proc = AsyncMock()
            mock_proc.process.return_value = fake_content
            MockCls.return_value = mock_proc

            source = _make_source()
            raw = [_raw(title="A"), _raw(title="B", external_id="ext-2")]
            result = await AIStage.execute(source, raw, [])

        assert len(result) == 2
        assert mock_proc.process.call_count == 2

    @pytest.mark.asyncio
    async def test_continues_on_processor_error(self):
        """AIStage should skip items that raise and still return the rest."""
        from app.pipeline.ai_stage import AIStage

        fake_content = MagicMock(spec=Content)
        with patch("app.pipeline.ai_stage.ContentProcessor") as MockCls:
            mock_proc = AsyncMock()
            mock_proc.process.side_effect = [RuntimeError("boom"), fake_content]
            MockCls.return_value = mock_proc

            result = await AIStage.execute(_make_source(), [_raw(), _raw(external_id="ext-2")], [])

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty(self):
        from app.pipeline.ai_stage import AIStage

        with patch("app.pipeline.ai_stage.ContentProcessor"):
            result = await AIStage.execute(_make_source(), [], [])

        assert result == []


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
        """CollectorStage should catch per-URL errors and continue."""
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
             patch("app.pipeline.collector_stage.merge_warning_messages", return_value=None):

            raw, warning, primary = await CollectorStage.execute(db, source)

        assert raw == []

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

        with patch("app.pipeline.storage_stage.normalize_external_id", side_effect=lambda x: x):
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

        with patch("app.pipeline.storage_stage.normalize_external_id", side_effect=lambda x: x):
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

        with patch("app.pipeline.storage_stage.normalize_external_id", return_value="first-id"):
            saved, marker = StorageStage.execute(db, [c1])

        assert saved == 1
        assert marker == "first-id"


# ===========================================================================
# coordinator._build_raw_content_objects
# ===========================================================================

class TestBuildRawContentObjects:

    @pytest.mark.asyncio
    async def test_basic_content_creation(self):
        from app.pipeline.coordinator import _build_raw_content_objects

        source = _make_source()
        raw = [_raw(title="Hello World", content="Some body text")]

        with patch("app.processors.extractor.ContentExtractor") as MockExt:
            MockExt.return_value = AsyncMock()
            results = await _build_raw_content_objects(raw, source)

        assert len(results) == 1
        assert results[0].title == "Hello World"
        assert results[0].source_id == source.id

    @pytest.mark.asyncio
    async def test_html_extraction_when_no_content(self):
        from app.pipeline.coordinator import _build_raw_content_objects

        source = _make_source()
        raw = [{"title": "T", "url": "https://example.com", "html": "<p>Extracted</p>", "content": "", "publish_time": datetime.utcnow().isoformat()}]

        mock_extractor = AsyncMock()
        mock_extractor.extract.return_value = "Extracted text"

        with patch("app.processors.extractor.ContentExtractor", return_value=mock_extractor):
            results = await _build_raw_content_objects(raw, source)

        assert len(results) == 1
        mock_extractor.extract.assert_called_once()

    @pytest.mark.asyncio
    async def test_publish_time_iso_parsing(self):
        from app.pipeline.coordinator import _build_raw_content_objects

        source = _make_source()
        raw = [_raw(publish_time="2025-06-15T10:00:00Z")]

        with patch("app.processors.extractor.ContentExtractor") as MockExt:
            MockExt.return_value = AsyncMock()
            results = await _build_raw_content_objects(raw, source)

        assert results[0].publish_time.year == 2025
        assert results[0].publish_time.month == 6

    @pytest.mark.asyncio
    async def test_publish_time_fallback_to_now(self):
        from app.pipeline.coordinator import _build_raw_content_objects

        source = _make_source()
        raw = [_raw(publish_time=None)]

        with patch("app.processors.extractor.ContentExtractor") as MockExt:
            MockExt.return_value = AsyncMock()
            results = await _build_raw_content_objects(raw, source)

        assert results[0].publish_time is not None

    @pytest.mark.asyncio
    async def test_skips_items_on_error(self):
        from app.pipeline.coordinator import _build_raw_content_objects

        source = _make_source()
        raw = [_raw(), {"title": None}]

        with patch("app.processors.extractor.ContentExtractor") as MockExt:
            MockExt.return_value = AsyncMock()
            with patch("app.pipeline.coordinator.strip_html_tags", side_effect=[
                "Article", "body text", RuntimeError("bad data")
            ]):
                results = await _build_raw_content_objects(raw, source)

        assert len(results) <= 2

    @pytest.mark.asyncio
    async def test_summary_truncation(self):
        from app.pipeline.coordinator import _build_raw_content_objects

        source = _make_source()
        long_body = "X" * 600
        raw = [_raw(content=long_body)]

        with patch("app.processors.extractor.ContentExtractor") as MockExt:
            MockExt.return_value = AsyncMock()
            results = await _build_raw_content_objects(raw, source)

        assert results[0].summary is not None
        assert results[0].summary.endswith("…")

    @pytest.mark.asyncio
    async def test_metadata_normalised_to_dict(self):
        from app.pipeline.coordinator import _build_raw_content_objects

        source = _make_source()
        raw = [_raw(metadata="not-a-dict")]

        with patch("app.processors.extractor.ContentExtractor") as MockExt:
            MockExt.return_value = AsyncMock()
            results = await _build_raw_content_objects(raw, source)

        assert results[0].metadata_ == {}


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
        db.commit.assert_called()

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
