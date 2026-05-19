"""Unit tests for :mod:`app.collectors.x_twitter_text`."""

from __future__ import annotations

from app.collectors.x_twitter_text import (
    build_api_since_id,
    build_title_from_text,
    build_x_cookie_items,
    clean_article_text,
    extract_article_urls,
    extract_tweet_id,
    extract_username_from_url,
    normalize_tweet_url,
    title_looks_like_url,
)


class TestExtractArticleUrls:
    def test_finds_article_url(self):
        text = "Read it here: https://x.com/i/article/1234567890"
        urls = extract_article_urls(text)
        assert urls == ["https://x.com/i/article/1234567890"]

    def test_promotes_to_https(self):
        text = "http://x.com/i/article/42"
        assert extract_article_urls(text) == ["https://x.com/i/article/42"]

    def test_accepts_twitter_host(self):
        urls = extract_article_urls("https://twitter.com/i/article/42")
        assert urls == ["https://twitter.com/i/article/42"]

    def test_dedupes(self):
        text = (
            "https://x.com/i/article/1 https://x.com/i/article/1 "
            "https://x.com/i/article/2"
        )
        assert extract_article_urls(text) == [
            "https://x.com/i/article/1",
            "https://x.com/i/article/2",
        ]

    def test_empty_input(self):
        assert extract_article_urls("") == []
        assert extract_article_urls(None) == []  # type: ignore[arg-type]


class TestExtractTweetId:
    def test_from_status_url(self):
        assert extract_tweet_id("https://x.com/user/status/1234567890") == "1234567890"

    def test_bare_id(self):
        assert extract_tweet_id("1234567890123") == "1234567890123"

    def test_id_with_prefix(self):
        assert extract_tweet_id("tag:twitter.com:1234567890abc") == "1234567890"

    def test_unmatched(self):
        assert extract_tweet_id("not an id at all") is None
        assert extract_tweet_id("") is None


class TestNormalizeTweetUrl:
    def test_rewrites_nitter_host(self):
        url = "https://nitter.example/user/status/123"
        assert normalize_tweet_url(url) == "https://x.com/user/status/123"

    def test_leaves_canonical_url(self):
        url = "https://x.com/user/status/42"
        assert normalize_tweet_url(url) == url

    def test_malformed_url_returned_unchanged(self):
        assert normalize_tweet_url("not a url") == "not a url"


class TestTitleHelpers:
    def test_title_looks_like_url(self):
        assert title_looks_like_url("https://example.com/a")
        assert not title_looks_like_url("A real human title")
        assert title_looks_like_url("")

    def test_build_title_skips_handles(self):
        text = "@elonmusk\n\nActually a thoughtful long article headline worth clicking"
        assert build_title_from_text(text).startswith("Actually")

    def test_build_title_skips_number_only_lines(self):
        text = "1.2万\n\nRealistic meaningful article headline length here"
        assert "Realistic" in build_title_from_text(text)

    def test_build_title_fallback_for_short_lines(self):
        # No substantial line exists so fallback joins first 80 chars
        text = "hi\nok\nabc"
        assert build_title_from_text(text)


class TestCleanArticleText:
    def test_returns_none_for_empty(self):
        assert clean_article_text("") is None
        assert clean_article_text(None) is None  # type: ignore[arg-type]

    def test_returns_none_when_too_short(self):
        assert clean_article_text("short body") is None

    def test_rejects_deny_markers(self):
        body = "This page is not supported." + " filler" * 100
        assert clean_article_text(body) is None

    def test_filters_nav_noise(self):
        body = (
            "Log in\nSign up\n@handle\n12.3万\n"
            + ("Long form article content that definitely goes well past the 280 character "
               "threshold so the helper returns a non-empty result. " * 4)
        )
        out = clean_article_text(body)
        assert out is not None
        assert "Log in" not in out
        assert "@handle" not in out


class TestCookieBuilders:
    def test_build_x_cookie_items_expands_domains(self):
        items = build_x_cookie_items({"auth_token": "abc", "ct0": "def"})
        names = [item["name"] for item in items]
        domains = {item["domain"] for item in items}
        assert names.count("auth_token") == 2  # x.com + .x.com
        assert domains == {"x.com", ".x.com"}

    def test_build_x_cookie_items_skips_empty(self):
        assert build_x_cookie_items({}) == []
        assert build_x_cookie_items({"": "x", "name": None}) == []  # type: ignore[dict-item]


class TestBuildApiSinceId:
    def test_returns_since_id_when_parseable(self):
        assert build_api_since_id("https://x.com/user/status/1234567890") == {"since_id": "1234567890"}

    def test_empty_when_none(self):
        assert build_api_since_id(None) == {}
        assert build_api_since_id("") == {}


class TestExtractUsername:
    def test_metadata_override(self):
        assert extract_username_from_url("https://example.com/x", {"username": "@alice"}) == "alice"

    def test_at_prefix(self):
        assert extract_username_from_url("@alice") == "alice"

    def test_from_twitter_url(self):
        assert extract_username_from_url("https://twitter.com/alice") == "alice"

    def test_from_x_url(self):
        assert extract_username_from_url("https://x.com/@bob") == "bob"

    def test_reserved_paths_return_none(self):
        assert extract_username_from_url("https://x.com/home") is None

    def test_bare_handle(self):
        assert extract_username_from_url("alice") == "alice"

    def test_unknown_returns_none(self):
        assert extract_username_from_url("https://other.example/path") is None
