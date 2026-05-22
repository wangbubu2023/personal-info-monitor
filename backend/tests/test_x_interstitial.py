"""Guards against X /status/ HTTP interstitial text polluting stored bodies."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domains.fetch.collectors.x_twitter_text import (
    is_x_status_page_url,
    looks_like_x_interstitial_text,
)


def test_is_x_status_page_url_detects_tweet_permalink():
    assert is_x_status_page_url("https://x.com/op7418/status/2057321749575020799")
    assert not is_x_status_page_url("https://x.com/i/article/123")


def test_looks_like_x_interstitial_text_detects_noscript_page():
    blob = (
        "We've detected that JavaScript is disabled in this browser. "
        "Please enable JavaScript or switch to a supported browser to continue using x.com. "
        "Terms of Service Privacy Policy © 2026 X Corp."
    )
    assert looks_like_x_interstitial_text(blob)
    assert not looks_like_x_interstitial_text("这个会打包成 Skill，任何 Agent 都能控制里面显示什么。")


@pytest.mark.asyncio
async def test_fetch_full_text_with_cookies_rejects_x_status_urls():
    from app.processors.content_processor import ContentProcessor

    processor = ContentProcessor()
    result = await processor._fetch_full_text_with_cookies(
        "https://x.com/op7418/status/2057321749575020799",
        {"auth_token": "x", "ct0": "y"},
    )
    assert result is None


@pytest.mark.asyncio
async def test_interstitial_repair_does_not_downgrade_to_shorter_title():
    """Regression: truncated listing title must not replace a longer interstitial body."""
    from app.domains.enrich.reader.body_loader import ensure_reader_body

    interstitial = (
        "We've detected that JavaScript is disabled in this browser. "
        "Please enable JavaScript or switch to a supported browser to continue using x.com. "
        "Terms of Service Privacy Policy © 2026 X Corp."
    )
    short_title = (
        "现在手上项目老多了： 1. Code Pilot 的重构马上就要完成了 "
        "2. 墨水屏的 Skills，应该今天或明天就能完成 3. 还有一个基于 PPT Sk..."
    )

    content = MagicMock()
    content.id = "cid-1"
    content.content_type = "x"
    content.source_id = "src-1"
    content.title = short_title
    content.full_content = interstitial
    content.summary = interstitial
    content.original_url = "https://x.com/op7418/status/2057326833499295978"
    content.metadata_ = {}
    content.translated_title = None

    db = AsyncMock()
    db.get = AsyncMock(return_value=None)
    db.commit = AsyncMock()

    with patch(
        "app.domains.fetch.tweet_repair.repair_x_tweet_content",
        new_callable=AsyncMock,
        return_value=False,
    ):
        with patch(
            "app.domains.enrich.reader.body_loader.load_source_cookies_for_reader",
            new_callable=AsyncMock,
            return_value={},
        ):
            with patch(
                "app.domains.enrich.reader.body_loader.fetch_x_article_fulltext",
                new_callable=AsyncMock,
                return_value="",
            ):
                with patch(
                    "app.domains.enrich.reader.body_loader._clean_x_reader_body",
                    return_value=interstitial,
                ):
                    body, _meta = await ensure_reader_body(content, db)

    assert body == interstitial
    assert content.full_content == interstitial

