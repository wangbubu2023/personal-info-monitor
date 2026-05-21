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
