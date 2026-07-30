"""Tests for ingest finalize article body fetch."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domains.fetch.article_body import ensure_article_body_during_finish, fetch_public_article_body
from app.platform.security.ssrf import PublicHttpTextResult


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


@pytest.mark.asyncio
async def test_fetch_public_article_body_prefers_structured_json():
    body = "Structured article body with enough meaningful context. " * 8
    html = f"""
    <html><head>
      <script type="application/ld+json">
      {{"@type": "NewsArticle", "articleBody": "{body}"}}
      </script>
    </head><body><p>Subscribe to continue</p></body></html>
    """

    with (
        patch(
            "app.domains.fetch.article_body.fetch_public_http_text",
            new_callable=AsyncMock,
            return_value=PublicHttpTextResult(200, "https://example.com/article", html),
        ),
        patch("app.domains.fetch.article_body.ContentExtractor") as mock_extractor,
    ):
        text, resolved_url = await fetch_public_article_body("https://example.com/article")

    assert "Structured article body" in text
    assert resolved_url == "https://example.com/article"
    mock_extractor.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_public_article_body_falls_back_when_structured_body_is_summary_sized():
    summary_body = "AI-style topic overview that is only a compressed summary of the article. " * 4
    readable_body = "Real article paragraph with reporting detail, author voice, and source evidence. " * 80
    html = f"""
    <html><head>
      <script type="application/ld+json">
      {{"@type": "NewsArticle", "articleBody": "{summary_body}"}}
      </script>
    </head><body><article>{readable_body}</article></body></html>
    """

    with (
        patch(
            "app.domains.fetch.article_body.fetch_public_http_text",
            new_callable=AsyncMock,
            return_value=PublicHttpTextResult(200, "https://example.com/article", html),
        ),
        patch("app.domains.fetch.article_body.ContentExtractor") as mock_extractor_cls,
    ):
        mock_extractor_cls.return_value.extract = AsyncMock(return_value=readable_body)

        text, resolved_url = await fetch_public_article_body("https://example.com/article")

    assert text.startswith("Real article paragraph")
    assert resolved_url == "https://example.com/article"
    mock_extractor_cls.return_value.extract.assert_awaited_once()


@pytest.mark.asyncio
async def test_fetch_public_article_body_automatically_retries_http_403():
    body = "Recovered article body with enough reporting detail and context. " * 8
    html = f"""
    <html><head>
      <script type="application/ld+json">
      {{"@type": "NewsArticle", "articleBody": "{body}"}}
      </script>
    </head><body></body></html>
    """
    fetch_mock = AsyncMock(
        side_effect=[
            PublicHttpTextResult(403, "https://example.com/article", ""),
            PublicHttpTextResult(200, "https://example.com/article", html),
        ]
    )

    with patch(
        "app.domains.fetch.article_body.fetch_public_http_text",
        fetch_mock,
    ):
        text, resolved_url = await fetch_public_article_body(
            "https://example.com/article"
        )

    assert text.startswith("Recovered article body")
    assert resolved_url == "https://example.com/article"
    assert fetch_mock.await_count == 2
