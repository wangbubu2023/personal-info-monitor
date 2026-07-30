from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.domains.fetch.collectors import bpc_strategies
from app.domains.fetch.collectors.website import WebsiteCollector
from app.models import Source
from app.models.source import SourceType


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


def test_playwright_interceptor_is_absent_when_no_patterns(monkeypatch):
    monkeypatch.setattr(bpc_strategies, "BLOCKED_PAYWALL_DOMAINS_AND_PATTERNS", ())
    assert bpc_strategies.get_bpc_playwright_interceptor({"bpc_block_paywalls": True}) is None


def test_automatic_profiles_are_bounded_and_preserve_authenticated_session():
    profiles = bpc_strategies.automatic_retry_profiles(
        {"fetch_strategy_mode": "auto", "bpc_random_ip": True},
        has_authenticated_session=True,
        reason="shell_page",
    )

    assert [name for name, _ in profiles] == [
        "search_referrer",
        "subscription_script_block",
    ]
    assert all("bpc_random_ip" not in metadata for _, metadata in profiles)
    assert all("bpc_ephemeral_context" not in metadata for _, metadata in profiles)
    assert all("bpc_spoof_ua" not in metadata for _, metadata in profiles)


def test_automatic_profiles_use_clean_context_only_for_anonymous_fetches():
    profiles = bpc_strategies.automatic_retry_profiles(
        {},
        has_authenticated_session=False,
        reason="http_status_403",
    )

    assert [name for name, _ in profiles] == [
        "crawler_compatibility",
        "clean_browser_context",
    ]
    assert profiles[0][1]["bpc_spoof_ua"] == "googlebot"
    assert "bpc_ephemeral_context" not in profiles[0][1]
    assert profiles[1][1]["bpc_ephemeral_context"] is True


@pytest.mark.parametrize("reason", ["http_status_429", "captcha", "login_required", "timeout"])
def test_automatic_profiles_do_not_retry_failures_headers_cannot_fix(reason):
    assert bpc_strategies.automatic_retry_profiles(
        {},
        has_authenticated_session=False,
        reason=reason,
    ) == []


def test_automatic_profiles_can_be_disabled_by_internal_policy():
    assert bpc_strategies.automatic_retry_profiles(
        {"fetch_strategy_mode": "off"},
        has_authenticated_session=False,
        reason="shell_page",
    ) == []


def test_normalize_strategy_metadata_migrates_legacy_switches_to_auto():
    normalized = bpc_strategies.normalize_fetch_strategy_metadata(
        {
            "rss_only": True,
            "bpc_spoof_ua": "googlebot",
            "bpc_random_ip": True,
            "source_stars": 3,
        }
    )

    assert normalized == {"fetch_strategy_mode": "auto", "source_stars": 3}


def test_normalize_strategy_metadata_preserves_internal_manual_mode():
    metadata = {
        "fetch_strategy_mode": "manual",
        "rss_only": True,
        "bpc_block_paywalls": True,
    }

    assert bpc_strategies.normalize_fetch_strategy_metadata(metadata) == metadata


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


@pytest.mark.asyncio
async def test_article_fetch_automatically_escalates_after_diagnosed_shell(monkeypatch):
    collector = WebsiteCollector()
    article_url = "https://example.com/article"
    fetch_once = AsyncMock(
        side_effect=[
            (None, article_url, "shell_page"),
            ("<html><article><p>body</p></article></html>", article_url, None),
        ]
    )
    monkeypatch.setattr(collector, "_fetch_article_html_once", fetch_once)

    result = await collector._fetch_article_html(
        article_url,
        {},
        "https://example.com",
        metadata={},
    )

    assert result[0]
    assert fetch_once.await_count == 2
    retry_metadata = fetch_once.await_args_list[1].kwargs["metadata"]
    assert retry_metadata["bpc_spoof_ua"] == "googlebot"
    assert retry_metadata["bpc_spoof_referer"] == "google"
    assert "bpc_random_ip" not in retry_metadata


@pytest.mark.asyncio
async def test_listing_fetch_automatically_records_successful_strategy(monkeypatch):
    collector = WebsiteCollector()
    source = Source(
        name="Blocked site",
        type=SourceType.WEBSITE,
        url="https://example.com",
        metadata={"fetch_strategy_mode": "auto"},
    )
    fetch_browser = AsyncMock(
        side_effect=[
            [],
            [
                {
                    "external_id": "story",
                    "title": "Recovered story",
                    "url": "https://example.com/story",
                }
            ],
        ]
    )
    monkeypatch.setattr(collector, "_fetch_with_playwright", fetch_browser)

    contents = await collector._fetch_with_automatic_browser_strategies(
        source,
        reason="html_parse_empty",
        has_authenticated_session=False,
    )

    assert contents[0]["title"] == "Recovered story"
    assert fetch_browser.await_count == 2
    assert source.metadata_["automatic_fetch_diagnostics"]["outcome"] == "succeeded"
    assert source.metadata_["automatic_fetch_diagnostics"]["strategy"] == "clean_browser_context"
