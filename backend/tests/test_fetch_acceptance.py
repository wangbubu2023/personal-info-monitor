"""Tests for ingest fetch acceptance gate."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domains.ingest.fetch_acceptance import (
    assess_fetch_acceptance,
    ensure_listing_summary,
    is_x_long_article,
    stamp_fetch_acceptance_metadata,
)
from app.domains.ingest.quality_metadata import FULLTEXT_STATUS_SUMMARY_ONLY


def _content(**kwargs):
    defaults = {
        "content_type": "website",
        "title": "OpenAI IPO",
        "summary": "OpenAI is reportedly preparing to file for an IPO with major banks.",
        "translated_summary": None,
        "full_content": "OpenAI is reportedly preparing to file for an IPO. " * 40,
        "original_url": "https://example.com/article",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_is_x_long_article_detects_article_url():
    content = _content(content_type="x", title="tweet", full_content="short")
    metadata = {"article_url": "https://x.com/i/article/12345"}
    assert is_x_long_article(content, metadata) is True


def test_is_x_long_article_false_for_plain_tweet():
    content = _content(content_type="x", title="Quick take", full_content="Just a short tweet.")
    assert is_x_long_article(content, {}) is False


def test_assess_fetch_acceptance_accepts_full_website_row():
    content = _content()
    metadata = {"fulltext_status": "full", "content_quality": 0.9}
    accepted, reason = assess_fetch_acceptance(content, metadata)
    assert accepted is True
    assert reason == "ok"


def test_assess_fetch_acceptance_rejects_long_flat_website_body():
    content = _content(full_content="这是一段被拍平的长正文。" * 140)
    metadata = {
        "fulltext_status": "partial",
        "content_quality": 0.5,
        "content_quality_signals": {
            "body_length": 2100,
            "paragraph_count": 1,
        },
    }

    accepted, reason = assess_fetch_acceptance(content, metadata)

    assert accepted is False
    assert reason == "suspicious_flat_text"


def test_assess_fetch_acceptance_accepts_summary_only_website():
    content = _content(full_content="Only the RSS description is available here for now and long enough.")
    metadata = {"fulltext_status": FULLTEXT_STATUS_SUMMARY_ONLY}
    accepted, reason = assess_fetch_acceptance(content, metadata)
    assert accepted is True
    assert reason == "ok"


def test_assess_fetch_acceptance_uses_longer_original_summary():
    content = _content(
        summary="OpenAI is reportedly preparing to file for an IPO with major banks involved.",
        translated_summary="OpenAI 拟 IPO。",
        full_content="OpenAI is reportedly preparing to file for an IPO. " * 40,
    )
    metadata = {"fulltext_status": "full"}
    accepted, reason = assess_fetch_acceptance(content, metadata)
    assert accepted is True
    assert reason == "ok"


def test_assess_fetch_acceptance_accepts_short_x_tweet():
    content = _content(
        content_type="x",
        title="Quick take",
        summary="",
        full_content="Just a short tweet about markets.",
    )
    accepted, reason = assess_fetch_acceptance(content, {})
    assert accepted is True
    assert reason == "ok"


def test_assess_fetch_acceptance_rejects_unhydrated_x_article():
    content = _content(
        content_type="x",
        title="https://x.com/i/article/12345",
        summary="",
        full_content="stub tweet with link",
        original_url="https://x.com/user/status/1",
    )
    metadata = {"article_url": "https://x.com/i/article/12345"}
    accepted, reason = assess_fetch_acceptance(content, metadata)
    assert accepted is False
    assert reason == "x_article_insufficient_body"


def test_assess_fetch_acceptance_accepts_hydrated_x_article():
    long_body = "This is a thoughtful long-form X article. " * 20
    content = _content(
        content_type="x",
        title="Thoughtful long-form headline",
        summary=long_body[:120],
        full_content=long_body,
        original_url="https://x.com/i/article/12345",
    )
    metadata = {"article_url": "https://x.com/i/article/12345", "article_fulltext": True}
    accepted, reason = assess_fetch_acceptance(content, metadata)
    assert accepted is True
    assert reason == "ok"


def test_ensure_listing_summary_derives_from_body():
    content = _content(summary="", full_content="Body text long enough to become a listing summary. " * 4)
    assert ensure_listing_summary(content) is True
    assert len(content.summary) >= 50


def test_stamp_fetch_incomplete_skips_scoring_fields():
    meta = stamp_fetch_acceptance_metadata(
        {"final_score": 88, "dimension_scores": {"impact": 8}},
        accepted=False,
        reason="insufficient_body_summary_only",
        source_stars=3,
    )
    assert meta["fetch_acceptance"] == "incomplete"
    assert meta["selection_status"] == "deferred"
    assert meta["scoring_method"] == "skipped_fetch_incomplete"
    assert "final_score" not in meta


@pytest.mark.asyncio
async def test_finish_content_skips_scoring_when_fetch_incomplete():
    mock_sem = MagicMock()
    mock_sem.__aenter__ = AsyncMock(return_value=None)
    mock_sem.__aexit__ = AsyncMock(return_value=False)

    mock_tracker = MagicMock()
    mock_tracker.start_process = AsyncMock()
    mock_tracker.end_process = AsyncMock()

    mock_source = SimpleNamespace(
        auth_config_id=None,
        metadata_={"source_stars": 3},
    )
    mock_content = MagicMock()
    mock_content.title = "RSS teaser only"
    mock_content.full_content = ""
    mock_content.summary = "Short teaser."
    mock_content.translated_summary = None
    mock_content.keyword_matches = []
    mock_content.metadata_ = {}
    mock_content.source = mock_source
    mock_content.content_type = "rss"
    mock_content.original_url = "https://example.com/article"
    mock_content.id = "content-1"

    mock_db = MagicMock()
    mock_db.query.return_value.options.return_value.filter.return_value.first.return_value = mock_content
    mock_db.close = MagicMock()
    mock_db.commit = MagicMock()

    with patch("app.domains.ingest.finish.get_llm_semaphore", return_value=mock_sem):
        with patch("app.domains.ingest.finish.task_tracker", mock_tracker):
            with patch("app.domains.ingest.finish.KEYWORD_MONITORING_ENABLED", False):
                with patch("app.database.SessionLocal", return_value=mock_db):
                    with patch(
                        "app.domains.fetch.article_body.ensure_content_bodies_during_finish",
                        new_callable=AsyncMock,
                    ):
                        from app.domains.ingest.finish import finish_content

                        await finish_content("content-1")

    assert mock_content.metadata_["fetch_acceptance"] == "incomplete"
    assert "final_score" not in mock_content.metadata_
    assert mock_content.metadata_["selection_status"] == "deferred"
