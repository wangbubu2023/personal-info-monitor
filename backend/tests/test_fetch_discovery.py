"""Tests for controlled listing-page discovery (rules + filtering)."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.domains.fetch.discovery import (
    DiscoveryRules,
    filter_candidates,
    parse_discovery_rules,
)


# --- rules parsing ----------------------------------------------------------


def test_parse_returns_none_without_discovery():
    assert parse_discovery_rules(None) is None
    assert parse_discovery_rules({}) is None
    assert parse_discovery_rules({"discovery": {"mode": "off"}}) is None


def test_parse_requires_listing_urls():
    assert parse_discovery_rules({"discovery": {"mode": "listing"}}) is None


def test_parse_basic_rules():
    rules = parse_discovery_rules(
        {
            "discovery": {
                "mode": "listing",
                "listing_urls": ["https://example.com/news"],
                "max_links": 5,
                "url_allow_patterns": ["/news/"],
                "url_deny_patterns": ["/login"],
                "freshness_days": 3,
            }
        }
    )
    assert isinstance(rules, DiscoveryRules)
    assert rules.enabled
    assert rules.max_links == 5
    assert rules.url_allow_patterns == ("/news/",)
    assert rules.url_deny_patterns == ("/login",)
    assert rules.freshness_days == 3


def test_parse_caps_max_links_and_depth():
    rules = parse_discovery_rules(
        {"discovery": {"mode": "listing", "listing_urls": ["https://e.com"], "max_links": 9999, "max_depth": 9}}
    )
    assert rules.max_links == 50  # ceiling
    assert rules.max_depth == 1  # recursion hard-capped


def test_parse_default_deny_patterns_applied():
    rules = parse_discovery_rules(
        {"discovery": {"mode": "listing", "listing_urls": ["https://e.com"]}}
    )
    assert "/login" in rules.url_deny_patterns
    assert "/tag/" in rules.url_deny_patterns


# --- candidate filtering ----------------------------------------------------


def _rules(**kwargs):
    base = dict(mode="listing", listing_urls=("https://example.com/news",))
    base.update(kwargs)
    return DiscoveryRules(**base)


def test_filter_same_domain_only():
    rules = _rules(url_deny_patterns=())
    candidates = [
        {"url": "https://example.com/news/a", "title": "Article A long title"},
        {"url": "https://other.com/news/b", "title": "Article B long title"},
    ]
    kept, diag = filter_candidates(candidates, rules, "https://example.com/news")
    assert len(kept) == 1
    assert kept[0].url == "https://example.com/news/a"
    assert diag["dropped_off_domain"] == 1


def test_filter_deny_pattern():
    rules = _rules(url_deny_patterns=("/login",))
    candidates = [
        {"url": "https://example.com/login", "title": "Login here please"},
        {"url": "https://example.com/news/ok", "title": "Real article title here"},
    ]
    kept, diag = filter_candidates(candidates, rules, "https://example.com/news")
    assert len(kept) == 1
    assert diag["dropped_deny"] == 1


def test_filter_allow_pattern_miss():
    rules = _rules(url_allow_patterns=("/news/",), url_deny_patterns=())
    candidates = [
        {"url": "https://example.com/news/keep", "title": "Keep this article"},
        {"url": "https://example.com/about/drop", "title": "Drop this about page"},
    ]
    kept, diag = filter_candidates(candidates, rules, "https://example.com/news")
    assert len(kept) == 1
    assert diag["dropped_allow_miss"] == 1


def test_filter_short_title():
    rules = _rules(min_title_chars=10, url_deny_patterns=())
    candidates = [
        {"url": "https://example.com/news/a", "title": "short"},
        {"url": "https://example.com/news/b", "title": "A sufficiently long title"},
    ]
    kept, diag = filter_candidates(candidates, rules, "https://example.com/news")
    assert len(kept) == 1
    assert diag["dropped_short_title"] == 1


def test_filter_dedupe():
    rules = _rules(url_deny_patterns=())
    candidates = [
        {"url": "https://example.com/news/a", "title": "Article A long title"},
        {"url": "https://example.com/news/a", "title": "Article A long title dupe"},
    ]
    kept, diag = filter_candidates(candidates, rules, "https://example.com/news")
    assert len(kept) == 1
    assert diag["dropped_duplicate"] == 1


def test_filter_freshness():
    now = datetime(2026, 6, 1, 12, 0, 0)
    rules = _rules(freshness_days=7, url_deny_patterns=())
    candidates = [
        {"url": "https://example.com/news/fresh", "title": "Fresh article here", "publish_time": now - timedelta(days=1)},
        {"url": "https://example.com/news/stale", "title": "Stale article here", "publish_time": now - timedelta(days=30)},
    ]
    kept, diag = filter_candidates(candidates, rules, "https://example.com/news", now=now)
    assert len(kept) == 1
    assert kept[0].url.endswith("/fresh")
    assert diag["dropped_stale"] == 1


def test_filter_max_links_truncation():
    rules = _rules(max_links=2, url_deny_patterns=())
    candidates = [
        {"url": f"https://example.com/news/a{i}", "title": f"Article number {i} title"}
        for i in range(5)
    ]
    kept, diag = filter_candidates(candidates, rules, "https://example.com/news")
    assert len(kept) == 2
    assert diag["truncated"] == 3
    assert diag["kept"] == 2
    assert diag["total"] == 5


def test_filter_relative_urls_resolved():
    rules = _rules(url_deny_patterns=())
    candidates = [{"url": "/news/relative", "title": "Relative link article"}]
    kept, _ = filter_candidates(candidates, rules, "https://example.com/news")
    assert kept[0].url == "https://example.com/news/relative"
