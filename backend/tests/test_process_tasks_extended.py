# backend/tests/test_process_tasks_extended.py
"""ingest.finish_content + tasks.process_tasks coverage (Phase 7 retired legacy aliases).

These tests used to import ``process_new_content`` / ``_process_new_content_async``
from :mod:`app.tasks.process_tasks` — those legacy names were removed in
Phase 7 and the canonical entry points
(:func:`app.domains.ingest.finish.finish_content` and friends) are imported
directly. The ``process_content`` (manual reprocess) and
``_update_keyword_matches_sync`` paths still live in
:mod:`app.tasks.process_tasks` and are imported from there.
"""

import asyncio
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_finish_content_content_not_found():
    """Missing content is a typed terminal failure, never a successful no-op."""
    mock_sem = MagicMock()
    mock_sem.__aenter__ = AsyncMock(return_value=None)
    mock_sem.__aexit__ = AsyncMock(return_value=False)

    mock_tracker = MagicMock()
    mock_tracker.start_process = AsyncMock()
    mock_tracker.end_process = AsyncMock()

    mock_db = MagicMock()
    mock_db.query.return_value.options.return_value.filter.return_value.first.return_value = None
    mock_db.close = MagicMock()

    with patch("app.domains.ingest.finish.get_llm_semaphore", return_value=mock_sem):
        with patch("app.domains.ingest.finish.task_tracker", mock_tracker):
            with patch("app.database.SessionLocal", return_value=mock_db):
                from app.domains.ingest.finish import finish_content
                from app.domains.ingest.failures import ContentNotFoundError
                with pytest.raises(ContentNotFoundError) as exc_info:
                    await finish_content("nonexistent-id")
                assert exc_info.value.failure.code.value == "CONTENT_NOT_FOUND"

    mock_tracker.start_process.assert_called_once()
    mock_tracker.end_process.assert_called_once()


@pytest.mark.asyncio
async def test_finish_content_keyword_matching():
    """Keyword matching runs when KEYWORD_MONITORING_ENABLED is True."""
    mock_sem = MagicMock()
    mock_sem.__aenter__ = AsyncMock(return_value=None)
    mock_sem.__aexit__ = AsyncMock(return_value=False)

    mock_tracker = MagicMock()
    mock_tracker.start_process = AsyncMock()
    mock_tracker.end_process = AsyncMock()

    mock_content = MagicMock()
    mock_content.id = "content-1"
    mock_content.content_type = "website"
    mock_content.title = "Test Title"
    mock_content.full_content = "Test content body with enough length for acceptance checks" * 3
    mock_content.summary = "Test summary with enough characters to pass listing checks easily."
    mock_content.translated_summary = None
    mock_content.translated_title = None
    mock_content.keyword_matches = []
    mock_content.metadata_ = {"fulltext_status": "full"}
    mock_content.original_url = "https://example.com/article"
    mock_content.source = None
    mock_content.auth_config_id = None

    mock_keyword = MagicMock()
    mock_keyword.enabled = True

    mock_db = MagicMock()
    mock_db.query.return_value.options.return_value.filter.return_value.first.return_value = mock_content
    mock_db.query.return_value.filter.return_value.all.return_value = [mock_keyword]
    mock_db.close = MagicMock()
    mock_db.commit = MagicMock()

    with patch("app.domains.ingest.finish.get_llm_semaphore", return_value=mock_sem):
        with patch("app.domains.ingest.finish.task_tracker", mock_tracker):
            with patch("app.domains.ingest.finish.KEYWORD_MONITORING_ENABLED", True):
                with patch("app.database.SessionLocal", return_value=mock_db):
                    with patch("app.domains.ingest.keywords.matcher.KeywordMatcher") as MockMatcher:
                        MockMatcher.return_value.match.return_value = [{"id": "kw-1", "keyword": "test"}]
                        with patch("app.domains.fetch.finalize.hydrate_fetched_content", new_callable=AsyncMock):
                            with patch(
                                "app.domains.ingest.finish._dispatch_keyword_alerts_async",
                                new=AsyncMock(),
                            ):
                                from app.domains.ingest.finish import finish_content
                                await finish_content("content-1")

    assert mock_content.keyword_matches == [{"id": "kw-1", "keyword": "test"}]


@pytest.mark.asyncio
async def test_finish_content_no_keywords_when_disabled():
    """Keyword matching is skipped when KEYWORD_MONITORING_ENABLED is False."""
    mock_sem = MagicMock()
    mock_sem.__aenter__ = AsyncMock(return_value=None)
    mock_sem.__aexit__ = AsyncMock(return_value=False)

    mock_tracker = MagicMock()
    mock_tracker.start_process = AsyncMock()
    mock_tracker.end_process = AsyncMock()

    mock_content = MagicMock()
    mock_content.title = "Test Title"
    mock_content.full_content = "Test content body"
    mock_content.summary = None
    mock_content.translated_summary = None
    mock_content.keyword_matches = []
    mock_content.metadata_ = {}
    mock_content.source = None
    mock_content.auth_config_id = None

    mock_db = MagicMock()
    mock_db.query.return_value.options.return_value.filter.return_value.first.return_value = mock_content
    mock_db.close = MagicMock()
    mock_db.commit = MagicMock()

    with patch("app.domains.ingest.finish.get_llm_semaphore", return_value=mock_sem):
        with patch("app.domains.ingest.finish.task_tracker", mock_tracker):
            with patch("app.domains.ingest.finish.KEYWORD_MONITORING_ENABLED", False):
                with patch("app.database.SessionLocal", return_value=mock_db):
                    with patch("app.domains.ingest.keywords.matcher.KeywordMatcher") as MockMatcher:
                        from app.domains.ingest.finish import finish_content
                        await finish_content("content-1")
                        # When disabled, KeywordMatcher class should never be instantiated
                        MockMatcher.assert_not_called()


@pytest.mark.asyncio
async def test_finish_content_stamps_baseline_score():
    mock_sem = MagicMock()
    mock_sem.__aenter__ = AsyncMock(return_value=None)
    mock_sem.__aexit__ = AsyncMock(return_value=False)

    mock_tracker = MagicMock()
    mock_tracker.start_process = AsyncMock()
    mock_tracker.end_process = AsyncMock()

    mock_source = SimpleNamespace(
        auth_config_id=None,
        metadata_={"source_stars": 3, "domain_focus": ["AI", "model"], "source_weight": 1.1},
    )
    mock_content = MagicMock()
    mock_content.title = "OpenAI releases new model"
    mock_content.full_content = "The new AI model improves developer workflows. " * 80
    mock_content.summary = "The new AI model improves developer workflows."
    mock_content.translated_summary = None
    mock_content.keyword_matches = []
    mock_content.metadata_ = {}
    mock_content.source = mock_source
    mock_content.auth_config_id = None

    mock_db = MagicMock()
    mock_db.query.return_value.options.return_value.filter.return_value.first.return_value = mock_content
    mock_db.close = MagicMock()
    mock_db.commit = MagicMock()

    with patch("app.domains.ingest.finish.get_llm_semaphore", return_value=mock_sem):
        with patch("app.domains.ingest.finish.task_tracker", mock_tracker):
            with patch("app.domains.ingest.finish.KEYWORD_MONITORING_ENABLED", False):
                with patch("app.database.SessionLocal", return_value=mock_db):
                    from app.domains.ingest.finish import finish_content
                    await finish_content("content-1")

    assert mock_content.metadata_["fulltext_status"] == "full"
    assert mock_content.metadata_["scoring_method"] == "rule"
    assert mock_content.metadata_["score_version"] == "pim-score-v2"
    assert mock_content.metadata_["lane"] == "tech_product"
    assert "final_score" in mock_content.metadata_
    assert mock_content.article_score == mock_content.metadata_["article_score"]
    assert mock_content.final_score == mock_content.metadata_["final_score"]
    assert mock_content.selection_status == mock_content.metadata_["selection_status"]
    assert mock_content.lane == "tech_product"
    assert "personalization" not in mock_content.metadata_


@pytest.mark.asyncio
async def test_finish_content_removes_stale_personalization_metadata():
    mock_sem = MagicMock()
    mock_sem.__aenter__ = AsyncMock(return_value=None)
    mock_sem.__aexit__ = AsyncMock(return_value=False)

    mock_tracker = MagicMock()
    mock_tracker.start_process = AsyncMock()
    mock_tracker.end_process = AsyncMock()

    mock_source = SimpleNamespace(
        auth_config_id=None,
        metadata_={"source_stars": 3, "domain_focus": ["AI", "model"], "source_weight": 1.1},
    )
    mock_content = MagicMock()
    mock_content.title = "OpenAI releases new model"
    mock_content.full_content = "The new AI model improves developer workflows. " * 80
    mock_content.summary = "The new AI model improves developer workflows."
    mock_content.translated_summary = None
    mock_content.keyword_matches = []
    mock_content.metadata_ = {"personalization": {"adjustment": 8.0}}
    mock_content.source = mock_source
    mock_content.auth_config_id = None

    mock_db = MagicMock()
    mock_db.query.return_value.options.return_value.filter.return_value.first.return_value = mock_content
    mock_db.close = MagicMock()
    mock_db.commit = MagicMock()

    with patch("app.domains.ingest.finish.get_llm_semaphore", return_value=mock_sem):
        with patch("app.domains.ingest.finish.task_tracker", mock_tracker):
            with patch("app.domains.ingest.finish.KEYWORD_MONITORING_ENABLED", False):
                with patch("app.database.SessionLocal", return_value=mock_db):
                    from app.domains.ingest.finish import finish_content
                    await finish_content("content-1")

    assert mock_content.metadata_["score_version"] == "pim-score-v2"
    assert "personalization" not in mock_content.metadata_
    assert mock_content.final_score == mock_content.metadata_["final_score"]


@pytest.mark.asyncio
async def test_finish_content_clears_suspicious_flat_full_content():
    mock_sem = MagicMock()
    mock_sem.__aenter__ = AsyncMock(return_value=None)
    mock_sem.__aexit__ = AsyncMock(return_value=False)

    mock_tracker = MagicMock()
    mock_tracker.start_process = AsyncMock()
    mock_tracker.end_process = AsyncMock()

    flat_body = "虎嗅正文被拍平成一段，没有任何真实段落边界。" * 160
    mock_source = SimpleNamespace(auth_config_id=None, metadata_={"source_stars": 3})
    mock_content = SimpleNamespace(
        id="content-flat",
        source_id="source-1",
        content_type="website",
        title="虎嗅长文",
        full_content=flat_body,
        summary="虎嗅长文摘要足够长，可以在正文被拒绝后作为列表摘要继续展示。",
        translated_summary=None,
        translated_title=None,
        keyword_matches=[],
        metadata_={"article_fulltext": True, "article_extract_method": "structured:json_ld"},
        original_url="https://example.com/article",
        source=mock_source,
        auth_config_id=None,
    )

    mock_db = MagicMock()
    mock_db.query.return_value.options.return_value.filter.return_value.first.return_value = mock_content
    mock_db.close = MagicMock()
    mock_db.commit = MagicMock()

    with patch("app.domains.ingest.finish.get_llm_semaphore", return_value=mock_sem):
        with patch("app.domains.ingest.finish.task_tracker", mock_tracker):
            with patch("app.domains.ingest.finish.KEYWORD_MONITORING_ENABLED", False):
                with patch("app.database.SessionLocal", return_value=mock_db):
                    with patch("app.domains.fetch.finalize.hydrate_fetched_content", new_callable=AsyncMock):
                        from app.domains.ingest.finish import finish_content

                        await finish_content("content-flat")

    assert mock_content.full_content is None
    assert mock_content.metadata_["fetch_acceptance"] == "incomplete"
    assert mock_content.metadata_["fetch_incomplete_reason"] == "suspicious_flat_text"
    assert mock_content.metadata_["selection_status"] == "deferred"
    assert mock_content.metadata_["rejected_full_content_chars"] == len(flat_body)
    assert mock_content.metadata_["rejected_full_content_reason"] == "suspicious_flat_text"
    assert mock_content.metadata_["fulltext_status"] == "summary_only"
    assert "article_fulltext" not in mock_content.metadata_


@pytest.mark.asyncio
async def test_process_content_not_found():
    """Manual reprocess: content not found logs error without exception."""
    mock_sem = MagicMock()
    mock_sem.__aenter__ = AsyncMock(return_value=None)
    mock_sem.__aexit__ = AsyncMock(return_value=False)

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None
    mock_db.close = MagicMock()

    with patch("app.tasks.process_tasks.get_llm_semaphore", return_value=mock_sem):
        with patch("app.database.SessionLocal", return_value=mock_db):
            from app.tasks.process_tasks import process_content
            await process_content("nonexistent-id")  # Must not raise


@pytest.mark.asyncio
async def test_dispatch_keyword_alerts_uses_create_task():
    content = SimpleNamespace(
        id="content-1",
        title="Test Title",
        keyword_matches=[{"id": "kw-1", "keyword": "AI"}, {"id": "kw-2", "keyword": "Ignored"}],
    )

    match_lookup = {
        "kw-1": SimpleNamespace(notify=True),
        "kw-2": SimpleNamespace(notify=False),
    }

    def _first_for_keyword():
        keyword_id = mock_db.query.return_value.filter.call_args[0][0].right.value
        return match_lookup[keyword_id]

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.side_effect = _first_for_keyword

    with patch(
        "app.domains.enrich.notifications.keyword_alert.send_keyword_alert",
        new=AsyncMock(),
    ) as mock_send:
        from app.domains.ingest.finish import _dispatch_keyword_alerts

        _dispatch_keyword_alerts(mock_db, content)
        await asyncio.sleep(0)

    mock_send.assert_awaited_once_with("content-1", "AI", "Test Title")


def test_update_keyword_matches_sync_uses_cursor_pagination():
    contents = [
        SimpleNamespace(
            id=f"{index:03d}",
            title=f"Title {index}",
            full_content="Body",
            summary=None,
            keyword_matches=[],
        )
        for index in range(205)
    ]
    keywords = [SimpleNamespace(enabled=True)]

    class FakeKeywordQuery:
        def filter(self, *_args, **_kwargs):
            return self

        def all(self):
            return keywords

    class FakeContentQuery:
        def __init__(self, rows):
            self._rows = rows
            self._last_seen = None
            self._limit = None
            self._limit_applied = False

        def order_by(self, *_args, **_kwargs):
            return self

        def limit(self, value):
            self._limit = value
            self._limit_applied = True
            return self

        def filter(self, expr):
            if self._limit_applied:
                raise AssertionError("filter must be applied before limit for cursor pagination")
            self._last_seen = expr.right.value
            return self

        def all(self):
            rows = self._rows
            if self._last_seen is not None:
                rows = [row for row in rows if row.id > self._last_seen]
            return rows[: self._limit]

    class FakeDB:
        def __init__(self):
            self.commit = MagicMock()
            self.close = MagicMock()

        def query(self, model):
            if model.__name__ == "Keyword":
                return FakeKeywordQuery()
            if model.__name__ == "Content":
                return FakeContentQuery(contents)
            raise AssertionError(f"Unexpected model: {model}")

    fake_db = FakeDB()

    with patch("app.tasks.process_tasks.KEYWORD_MONITORING_ENABLED", True):
        with patch("app.database.SessionLocal", return_value=fake_db):
            with patch("app.domains.ingest.keywords.matcher.KeywordMatcher") as MockMatcher:
                MockMatcher.return_value.match.return_value = [{"id": "kw-1", "keyword": "test"}]
                from app.tasks.process_tasks import _update_keyword_matches_sync

                _update_keyword_matches_sync()

    assert fake_db.commit.call_count == 3
    assert all(content.keyword_matches == [{"id": "kw-1", "keyword": "test"}] for content in contents)


@pytest.mark.asyncio
async def test_batch_process_contents_honours_reprocess_flags():
    """reprocess flags must drive a real process_content call, not be ignored."""
    from app.tasks import process_tasks

    with patch.object(process_tasks, "process_content", new=AsyncMock()) as mock_proc:
        with patch("app.tasks.task_queue.task_queue") as mock_queue:
            mock_queue.enqueue_ingest_finish_many = AsyncMock()
            await process_tasks.batch_process_contents(
                ["a", "b"], regenerate_summary=True, retranslate=False
            )

    assert mock_proc.await_count == 2
    mock_proc.assert_any_await("a", regenerate_summary=True, retranslate=False)
    mock_proc.assert_any_await("b", regenerate_summary=True, retranslate=False)
    mock_queue.enqueue_ingest_finish_many.assert_not_called()


@pytest.mark.asyncio
async def test_batch_process_contents_without_flags_enqueues_finish():
    """With no reprocess flag set it stays the lightweight ingest-finish path."""
    from app.tasks import process_tasks

    with patch.object(process_tasks, "process_content", new=AsyncMock()) as mock_proc:
        with patch("app.tasks.task_queue.task_queue") as mock_queue:
            mock_queue.enqueue_ingest_finish_many = AsyncMock(return_value=2)
            await process_tasks.batch_process_contents(["a", "b"])

    mock_proc.assert_not_awaited()
    mock_queue.enqueue_ingest_finish_many.assert_awaited_once_with(["a", "b"], job_id=None)
