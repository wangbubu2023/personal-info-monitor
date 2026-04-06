# backend/tests/test_process_tasks_extended.py
"""process_tasks coverage: normal path, content not found, keyword matching."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_process_new_content_content_not_found():
    """When content doesn't exist, logs error and returns without exception."""
    mock_sem = MagicMock()
    mock_sem.__aenter__ = AsyncMock(return_value=None)
    mock_sem.__aexit__ = AsyncMock(return_value=False)

    mock_tracker = MagicMock()
    mock_tracker.start_process = AsyncMock()
    mock_tracker.end_process = AsyncMock()

    mock_db = MagicMock()
    mock_db.query.return_value.options.return_value.filter.return_value.first.return_value = None
    mock_db.close = MagicMock()

    with patch("app.tasks.process_tasks.get_llm_semaphore", return_value=mock_sem):
        with patch("app.tasks.process_tasks.task_tracker", mock_tracker):
            with patch("app.database.SessionLocal", return_value=mock_db):
                from app.tasks.process_tasks import process_new_content
                await process_new_content("nonexistent-id")  # Must not raise

    mock_tracker.start_process.assert_called_once()
    mock_tracker.end_process.assert_called_once()


@pytest.mark.asyncio
async def test_process_new_content_keyword_matching():
    """Keyword matching runs when KEYWORD_MONITORING_ENABLED is True."""
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
    mock_content.keyword_matches = []
    mock_content.metadata_ = {}
    mock_content.source = None
    mock_content.auth_config_id = None

    mock_keyword = MagicMock()
    mock_keyword.enabled = True

    mock_db = MagicMock()
    mock_db.query.return_value.options.return_value.filter.return_value.first.return_value = mock_content
    mock_db.query.return_value.filter.return_value.all.return_value = [mock_keyword]
    mock_db.close = MagicMock()
    mock_db.commit = MagicMock()

    with patch("app.tasks.process_tasks.get_llm_semaphore", return_value=mock_sem):
        with patch("app.tasks.process_tasks.task_tracker", mock_tracker):
            with patch("app.tasks.process_tasks.KEYWORD_MONITORING_ENABLED", True):
                with patch("app.database.SessionLocal", return_value=mock_db):
                    with patch("app.processors.keyword_matcher.KeywordMatcher") as MockMatcher:
                        MockMatcher.return_value.match.return_value = [{"id": "kw-1", "keyword": "test"}]
                        with patch("app.tasks.process_tasks._dispatch_keyword_alerts"):
                            from app.tasks.process_tasks import process_new_content
                            await process_new_content("content-1")

    assert mock_content.keyword_matches == [{"id": "kw-1", "keyword": "test"}]


@pytest.mark.asyncio
async def test_process_new_content_no_keywords_when_disabled():
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
    mock_content.keyword_matches = []
    mock_content.metadata_ = {}
    mock_content.source = None
    mock_content.auth_config_id = None

    mock_db = MagicMock()
    mock_db.query.return_value.options.return_value.filter.return_value.first.return_value = mock_content
    mock_db.close = MagicMock()
    mock_db.commit = MagicMock()

    with patch("app.tasks.process_tasks.get_llm_semaphore", return_value=mock_sem):
        with patch("app.tasks.process_tasks.task_tracker", mock_tracker):
            with patch("app.tasks.process_tasks.KEYWORD_MONITORING_ENABLED", False):
                with patch("app.database.SessionLocal", return_value=mock_db):
                    with patch("app.processors.keyword_matcher.KeywordMatcher") as MockMatcher:
                        from app.tasks.process_tasks import process_new_content
                        await process_new_content("content-1")
                        # When disabled, KeywordMatcher class should never be instantiated
                        MockMatcher.assert_not_called()


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
