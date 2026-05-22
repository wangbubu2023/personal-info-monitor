"""Tests for X tweet body repair (GraphQL + public API fallback)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domains.fetch.tweet_repair import fetch_x_tweet_public, repair_x_tweet_content


@pytest.mark.asyncio
async def test_fetch_x_tweet_public_parses_fxtwitter_payload():
    payload = {
        "code": 200,
        "tweet": {
            "text": "完整推文正文\n\n1. 第一项\n2. 第二项",
            "url": "https://x.com/op7418/status/123",
        },
    }

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value=payload)
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.get = MagicMock(return_value=mock_response)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("app.domains.fetch.tweet_repair.aiohttp.ClientSession", return_value=mock_session):
        item = await fetch_x_tweet_public("op7418", "123")

    assert item is not None
    assert "完整推文正文" in item["content"]
    assert item["metadata"]["source_strategy"] == "fxtwitter_public"


@pytest.mark.asyncio
async def test_repair_x_tweet_content_upgrades_truncated_body():
    content = MagicMock()
    content.id = "cid-1"
    content.content_type = "x"
    content.external_id = "2057326833499295978"
    content.original_url = "https://x.com/op7418/status/2057326833499295978"
    content.title = "短标题..."
    content.full_content = "短标题..."
    content.summary = "短标题..."
    content.metadata_ = {"x_interstitial_repaired_at": "2026-05-21T00:00:00"}

    full_body = (
        "现在手上项目老多了：\n\n"
        "1. Code Pilot 的重构马上就要完成了\n"
        "2. 墨水屏的 Skills，应该今天或明天就能完成\n"
        "3. 还有一个基于 PPT Skills 的项目"
    )
    with patch(
        "app.domains.fetch.tweet_repair.refetch_x_tweet_from_source",
        new_callable=AsyncMock,
        return_value={
            "content": full_body,
            "title": "现在手上项目老多了：",
            "metadata": {"source_strategy": "fxtwitter_public"},
        },
    ):
        ok = await repair_x_tweet_content(content, None)

    assert ok is True
    assert content.full_content == full_body
    assert "x_tweet_repaired_at" in content.metadata_
    assert content.metadata_["x_tweet_repair_strategy"] == "fxtwitter_public"
    assert "x_interstitial_repaired_at" not in content.metadata_


@pytest.mark.asyncio
async def test_repair_x_tweet_content_skips_when_not_longer():
    existing = "x" * 200
    content = MagicMock()
    content.id = "cid-2"
    content.content_type = "x"
    content.external_id = "1"
    content.original_url = "https://x.com/u/status/1"
    content.title = existing
    content.full_content = existing
    content.summary = existing
    content.metadata_ = {}

    with patch(
        "app.domains.fetch.tweet_repair.refetch_x_tweet_from_source",
        new_callable=AsyncMock,
        return_value={"content": existing, "title": "t"},
    ):
        ok = await repair_x_tweet_content(content, None)

    assert ok is False
