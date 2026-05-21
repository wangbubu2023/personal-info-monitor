"""Tests for normalize_source_url_for_dedupe."""

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
    b = normalize_source_url_for_dedupe("https://www.example.com/path")
    assert a == b


def test_preserves_query():
    assert "foo=1" in normalize_source_url_for_dedupe("https://a.com/x?foo=1")


def test_normalize_source_url_input_prepends_https():
    assert normalize_source_url_input("www.bbc.com/zhongwen/simp") == (
        "https://www.bbc.com/zhongwen/simp"
    )


def test_normalize_source_url_input_preserves_explicit_scheme():
    assert normalize_source_url_input("http://example.com") == "http://example.com"


def test_canonical_article_external_id_wordpress_p_and_slug_match():
    wp = "https://www.theverge.com/?p=934521"
    slug = (
        "https://www.theverge.com/ai-artificial-intelligence/934521/"
        "google-synthid-c2pa-content-credentials-ai-labelling-efforts"
    )
    assert canonical_article_external_id(wp) == canonical_article_external_id(slug)
    assert canonical_article_external_id(wp) == "https://theverge.com/article:934521"
