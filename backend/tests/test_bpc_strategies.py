from __future__ import annotations

import pytest

from app.domains.fetch.collectors import bpc_strategies
from app.domains.fetch.collectors.website import WebsiteCollector


def test_spoofed_headers_reject_control_char_custom_values():
    headers = bpc_strategies.get_spoofed_headers(
        {
            "bpc_custom_ua": "Bad\nUA",
            "bpc_custom_referer": "https://example.com/\r\nX-Test: 1",
        },
        "Default UA",
    )

    assert headers["User-Agent"] == "Default UA"
    assert "Referer" not in headers


def test_playwright_interceptor_is_absent_until_paywall_blocking_enabled():
    assert bpc_strategies.get_bpc_playwright_interceptor({}) is None
    assert bpc_strategies.get_bpc_playwright_interceptor({"bpc_block_paywalls": True}) is not None


@pytest.mark.asyncio
async def test_bpc_browser_strategy_triggers_playwright_without_cookies(monkeypatch):
    collector = WebsiteCollector()
    captured: dict[str, object] = {}

    async def fake_fetch(article_url, cookies, source_url, browser_session=None, metadata=None):
        captured["cookies"] = cookies
        captured["metadata"] = metadata
        return "<html>ok</html>", article_url, None

    monkeypatch.setattr(collector, "_fetch_article_html_with_playwright", fake_fetch)

    result = await collector._attempt_playwright_article_html(
        "https://example.com/article",
        {},
        "https://example.com",
        metadata={"bpc_block_paywalls": True},
    )

    assert result == ("<html>ok</html>", "https://example.com/article", None)
    assert captured["cookies"] == {}
    assert captured["metadata"] == {"bpc_block_paywalls": True}


@pytest.mark.asyncio
async def test_bpc_ephemeral_context_strips_cookies_before_playwright(monkeypatch):
    collector = WebsiteCollector()
    captured: dict[str, object] = {}

    async def fake_fetch(article_url, cookies, source_url, browser_session=None, metadata=None):
        captured["cookies"] = cookies
        return "<html>ok</html>", article_url, None

    monkeypatch.setattr(collector, "_fetch_article_html_with_playwright", fake_fetch)

    await collector._attempt_playwright_article_html(
        "https://example.com/article",
        {"sid": "secret"},
        "https://example.com",
        metadata={"bpc_ephemeral_context": True},
    )

    assert captured["cookies"] == {}


@pytest.mark.asyncio
async def test_article_playwright_still_skips_without_session_or_browser_strategy():
    collector = WebsiteCollector()

    assert (
        await collector._attempt_playwright_article_html(
            "https://example.com/article",
            {},
            "https://example.com",
            metadata={},
        )
        is None
    )
