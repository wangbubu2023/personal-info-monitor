"""Tests for normalize_source_url_for_dedupe."""

import pytest

from app.utils.url import (
    canonical_article_external_id,
    normalize_source_url_for_dedupe,
    normalize_source_url_input,
)


def test_trailing_slash_equivalence():
    assert normalize_source_url_for_dedupe("https://www.huxiu.com/") == normalize_source_url_for_dedupe(
        "https://www.huxiu.com"
    )


def test_scheme_and_host_case():
    a = normalize_source_url_for_dedupe("HTTPS://WWW.Example.COM/path/")
    b = normalize_source_url_for_dedupe("http://example.com/path")
    assert a == b


def test_preserves_non_tracking_query():
    assert "foo=1" in normalize_source_url_for_dedupe("https://a.com/x?foo=1")


def test_strips_tracking_query_and_fragment():
    a = normalize_source_url_for_dedupe("https://www.example.com/post?utm_source=x&fbclid=abc&from=timeline&id=7#comments")
    b = normalize_source_url_for_dedupe("http://example.com/post?id=7")
    assert a == b
    assert a == "https://example.com/post?id=7"


def test_strips_amp_path_suffix():
    assert normalize_source_url_for_dedupe("https://example.com/news/story/amp") == (
        "https://example.com/news/story"
    )


def test_strips_amp_subdomain():
    assert normalize_source_url_for_dedupe("https://amp.example.com/news/story?utm_medium=social") == (
        "https://example.com/news/story"
    )


def test_normalize_source_url_input_prepends_https():
    assert normalize_source_url_input("www.bbc.com/zhongwen/simp") == (
        "https://www.bbc.com/zhongwen/simp"
    )


def test_normalize_source_url_input_preserves_explicit_scheme():
    assert normalize_source_url_input("http://example.com") == "http://example.com"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, ""),
        ("", ""),
        ("EXAMPLE", "example"),
        (" http://www.example.com/path/ ", "https://example.com/path"),
        ("HTTPS://WWW.Example.COM/path/", "https://example.com/path"),
        ("https://example.com//a///b", "https://example.com/a/b"),
        ("https://example.com", "https://example.com/"),
        ("http://example.com:80/a", "https://example.com/a"),
        ("https://example.com:443/a", "https://example.com/a"),
        ("https://example.com:8443/a", "https://example.com:8443/a"),
        ("https://example.com/a?b=2&a=1", "https://example.com/a?a=1&b=2"),
        ("https://example.com/a?tag=ai&tag=policy", "https://example.com/a?tag=ai&tag=policy"),
        ("https://example.com/a?flag=", "https://example.com/a?flag="),
        ("https://example.com/a#comments", "https://example.com/a"),
        ("https://example.com/a?utm_source=x&id=7", "https://example.com/a?id=7"),
        ("https://example.com/a?UTM_MEDIUM=x&id=7", "https://example.com/a?id=7"),
        ("https://example.com/a?fbclid=x&id=7", "https://example.com/a?id=7"),
        ("https://example.com/a?gclid=x&id=7", "https://example.com/a?id=7"),
        ("https://example.com/a?igshid=x&id=7", "https://example.com/a?id=7"),
        ("https://example.com/a?mc_cid=x&id=7", "https://example.com/a?id=7"),
        ("https://example.com/a?mc_eid=x&id=7", "https://example.com/a?id=7"),
        ("https://example.com/a?mkt_tok=x&id=7", "https://example.com/a?id=7"),
        ("https://example.com/a?ref=x&id=7", "https://example.com/a?id=7"),
        ("https://example.com/a?source=x&id=7", "https://example.com/a?id=7"),
        ("https://example.com/a?spm=x&id=7", "https://example.com/a?id=7"),
        ("https://example.com/a?vero_id=x&id=7", "https://example.com/a?id=7"),
        ("https://example.com/a?yclid=x&id=7", "https://example.com/a?id=7"),
        ("https://example.com/a?from=timeline&id=7", "https://example.com/a?id=7"),
        ("https://example.com/amp/news/story", "https://example.com/news/story"),
        ("https://example.com/news/story/amp", "https://example.com/news/story"),
        ("https://amp.example.com/news/story", "https://example.com/news/story"),
        ("https://www.amp.example.com/news/story", "https://example.com/news/story"),
        ("https://example.com/feed?category=world&utm_campaign=x", "https://example.com/feed?category=world"),
        ("https://example.com/search?q=ai%20policy&utm_content=card", "https://example.com/search?q=ai+policy"),
    ],
)
def test_normalize_source_url_for_dedupe_table(raw, expected):
    assert normalize_source_url_for_dedupe(raw) == expected


def test_canonical_article_external_id_wordpress_p_and_slug_match():
    wp = "https://www.theverge.com/?p=934521"
    slug = (
        "https://www.theverge.com/ai-artificial-intelligence/934521/"
        "google-synthid-c2pa-content-credentials-ai-labelling-efforts"
    )
    assert canonical_article_external_id(wp) == canonical_article_external_id(slug)
    assert canonical_article_external_id(wp) == "https://theverge.com/article:934521"


def test_canonical_article_external_id_does_not_collapse_date_path_segments():
    a = canonical_article_external_id("https://example.com/news/20260630/a?utm_campaign=x")
    b = canonical_article_external_id("http://www.example.com/news/20260630/b")
    assert a == "https://example.com/news/20260630/a"
    assert b == "https://example.com/news/20260630/b"
    assert a != b


def test_canonical_article_external_id_collapses_non_date_article_ids():
    assert canonical_article_external_id("http://www.example.com/articles/123456?utm_source=x") == (
        "https://example.com/article:123456"
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", ""),
        ("https://www.example.com/?p=12345&utm_source=x", "https://example.com/article:12345"),
        ("https://example.com/article/12345", "https://example.com/article:12345"),
        ("https://example.com/posts/12345/story-title", "https://example.com/article:12345"),
        ("https://example.com/news/12345/market-update", "https://example.com/article:12345"),
        ("https://example.com/news/20260630/market-update", "https://example.com/news/20260630/market-update"),
        ("https://amp.example.com/news/story?from=timeline", "https://example.com/news/story"),
        ("https://www.example.com/news/story/amp?utm_medium=social", "https://example.com/news/story"),
    ],
)
def test_canonical_article_external_id_table(raw, expected):
    assert canonical_article_external_id(raw) == expected
