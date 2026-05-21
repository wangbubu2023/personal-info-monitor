"""Tests for ingest finalize article body fetch."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domains.fetch.article_body import ensure_article_body_during_finish


@pytest.mark.asyncio
async def test_ensure_article_body_during_finish_upgrades_short_rows():
    content = MagicMock()
    content.id = "cid-1"
    content.content_type = "website"
    content.original_url = "https://www.engadget.com/article"
    content.full_content = ""
    content.summary = ""
    content.title = "OpenAI IPO"
    content.translated_summary = None
    content.metadata_ = {"ingest_finalize_pending": True}

    long_body = "OpenAI is reportedly preparing to file for an IPO. " * 40
    with patch(
        "app.domains.fetch.article_body.fetch_public_article_body",
        new_callable=AsyncMock,
        return_value=(long_body, content.original_url),
    ):
        with patch(
            "app.domains.fetch.article_body.truncate_content",
            return_value=long_body,
        ):
            assert await ensure_article_body_during_finish(content) is True

    assert content.full_content == long_body
    assert content.metadata_.get("article_fulltext") is True
    assert content.metadata_.get("ingest_body_fetched_at")
