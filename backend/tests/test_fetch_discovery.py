"""Tests for controlled listing-page discovery (rules + filtering)."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.domains.fetch.discovery import (
    DiscoveryRules,
    default_discovery_rules,
    discovery_diagnostics_metadata,
    expand_listing_urls,
    filter_candidates,
    parse_discovery_rules,
    record_discovery_diagnostics,
    resolve_discovery_rules,
)
from app.interfaces.http.sources._helpers import serialize_source
from app.models.source import Source, SourceType


# --- rules parsing ----------------------------------------------------------


def test_parse_returns_none_without_discovery():
    assert parse_discovery_rules(None) is None
    assert parse_discovery_rules({}) is None
    assert parse_discovery_rules({"discovery": {"mode": "off"}}) is None


def test_resolve_uses_default_rules_without_explicit_discovery():
    rules = resolve_discovery_rules("https://example.com/news", {})
    assert isinstance(rules, DiscoveryRules)
    assert rules.enabled
    assert rules.listing_urls == ("https://example.com/news",)
    assert rules.require_article_url is True
    assert rules.fallback_to_static_on_empty is True
    assert rules.extra["default"] is True


def test_default_discovery_can_be_disabled():
    assert resolve_discovery_rules("https://example.com/news", {"discovery": {"mode": "off"}}) is None
    assert default_discovery_rules("https://example.com/news", {"listing_discovery": False}) is None


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


def test_parse_expands_paginated_listing_urls_with_default_page_param():
    rules = parse_discovery_rules(
        {
            "discovery": {
                "mode": "listing",
                "listing_urls": [
                    "https://example.com/news",
                    "https://example.com/business?region=us",
                ],
                "pagination_max_pages": 3,
            }
        }
    )
    assert isinstance(rules, DiscoveryRules)
    assert expand_listing_urls(rules) == (
        "https://example.com/news",
        "https://example.com/news?page=2",
        "https://example.com/news?page=3",
        "https://example.com/business?region=us",
        "https://example.com/business?region=us&page=2",
        "https://example.com/business?region=us&page=3",
    )


def test_parse_expands_paginated_listing_urls_with_template():
    rules = parse_discovery_rules(
        {
            "discovery": {
                "mode": "listing",
                "listing_urls": ["https://example.com/news"],
                "pagination_max_pages": 3,
                "pagination_url_template": "https://example.com/news/page/{page}",
            }
        }
    )
    assert isinstance(rules, DiscoveryRules)
    assert expand_listing_urls(rules) == (
        "https://example.com/news",
        "https://example.com/news/page/2",
        "https://example.com/news/page/3",
    )


def test_default_discovery_accepts_coverage_listing_urls_and_pagination():
    rules = default_discovery_rules(
        "https://example.com",
        {
            "discovery_default_listing_urls": [
                "https://example.com/news",
                "https://example.com/world",
            ],
            "discovery_default_pagination_max_pages": 2,
        },
    )
    assert isinstance(rules, DiscoveryRules)
    assert rules.extra["default"] is True
    assert expand_listing_urls(rules) == (
        "https://example.com/news",
        "https://example.com/news?page=2",
        "https://example.com/world",
        "https://example.com/world?page=2",
    )


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


def test_filter_default_rules_require_article_urls():
    rules = default_discovery_rules("https://example.com/news")
    candidates = [
        {"url": "https://example.com/topics/ai", "title": "Artificial intelligence topic"},
        {"url": "https://example.com/articles/new-chip-breakthrough", "title": "New chip breakthrough reported"},
    ]
    kept, diag = filter_candidates(candidates, rules, "https://example.com/news")
    assert [article.url for article in kept] == ["https://example.com/articles/new-chip-breakthrough"]
    assert diag["dropped_non_article_url"] == 1


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


def _orm_source(metadata=None):
    return Source(
        name="Example",
        type=SourceType.WEBSITE,
        url="https://example.com/news",
        fetch_interval=60,
        enabled=True,
        auth_required=False,
        error_count=0,
        metadata_=dict(metadata or {}),
    )


def test_record_discovery_diagnostics_mirrors_structured_source_columns():
    source = _orm_source()

    payload = record_discovery_diagnostics(
        source,
        {
            "total": 10,
            "kept": 3,
            "dropped_no_url": 1,
            "dropped_off_domain": 2,
            "dropped_deny": 1,
            "dropped_allow_miss": 0,
            "dropped_non_article_url": 1,
            "dropped_short_title": 1,
            "dropped_duplicate": 1,
            "dropped_stale": 0,
            "truncated": 0,
            "listing_urls_configured": 2,
            "listing_pages_total": 4,
            "listing_pages_fetched": 3,
            "listing_pages_failed": 1,
            "pagination_max_pages": 2,
        },
    )

    assert payload["checked_at"]
    assert source.discovery_checked_at is not None
    assert source.discovery_total == 10
    assert source.discovery_kept == 3
    assert source.discovery_dropped_non_article_url == 1
    assert source.discovery_listing_pages_total == 4
    assert source.discovery_listing_pages_failed == 1
    assert source.metadata_["discovery_diagnostics"]["kept"] == 3


def test_structured_discovery_diagnostics_are_authoritative_for_source_serialization():
    source = _orm_source({"discovery_diagnostics": {"total": 999, "kept": 999}})
    record_discovery_diagnostics(source, {"total": 5, "kept": 2, "listing_pages_total": 1})

    diagnostics = discovery_diagnostics_metadata(source)
    serialized = serialize_source(source)

    assert diagnostics["total"] == 5
    assert diagnostics["kept"] == 2
    assert serialized["metadata"]["discovery_diagnostics"]["total"] == 5
    assert serialized["metadata"]["discovery_diagnostics"]["kept"] == 2
