"""Tests for normalize_source_url_for_dedupe."""

from app.utils.url import normalize_source_url_for_dedupe, normalize_source_url_input


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
