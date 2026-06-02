"""Tests for the explainable full-text quality layer."""

from __future__ import annotations

from app.domains.fetch.fulltext_quality import assess_fulltext_quality


def test_full_article():
    body = "This is a real article paragraph with substance. " * 60
    q = assess_fulltext_quality(title="Big News", body=body, url="https://example.com/news/big-news")
    assert q.status == "full"
    assert q.score >= 0.78
    assert q.coarse_status() == "full"
    assert not q.is_blocked()


def test_partial_article():
    body = "A medium length body. " * 25  # ~500 chars
    q = assess_fulltext_quality(title="Story", body=body, url="https://example.com/article/story")
    assert q.status == "partial"
    assert q.coarse_status() == "partial"


def test_login_required_short_body():
    q = assess_fulltext_quality(
        title="Members only",
        body="Please sign in to continue reading this article.",
        url="https://example.com/article/x",
    )
    assert q.status == "login_required"
    assert q.is_blocked()
    assert q.coarse_status() == "blocked"


def test_paywall_detected():
    q = assess_fulltext_quality(
        title="Premium",
        body="This article is for subscribers. To continue reading, become a member.",
        url="https://example.com/p/1",
    )
    assert q.status == "login_required"


def test_captcha_detected():
    q = assess_fulltext_quality(
        title="",
        body="Please complete the captcha to verify you are human.",
        url="https://example.com/a",
    )
    assert q.status == "captcha"
    assert q.is_blocked()


def test_bot_wall_detected():
    q = assess_fulltext_quality(
        title="",
        body="Access denied. Checking your browser before accessing. Cloudflare.",
        url="https://example.com/a",
    )
    assert q.status == "bot_wall"


def test_long_body_mentioning_captcha_not_flagged():
    body = ("A thorough investigative report about online security and the use of captcha systems. " * 40)
    q = assess_fulltext_quality(title="Captcha report", body=body, url="https://example.com/news/captcha")
    assert q.status == "full"


def test_boilerplate_only_page():
    body = "Home\nMenu\nSearch\nSubscribe\nPrivacy Policy\nTerms of Service\n© 2026 All rights reserved"
    q = assess_fulltext_quality(title="Site", body=body, url="https://example.com/")
    assert q.status == "boilerplate_only"
    assert q.boilerplate_ratio is not None and q.boilerplate_ratio >= 0.5


def test_non_article_listing_page():
    q = assess_fulltext_quality(
        title="Latest Headlines Index",
        body="Some short unrelated navigation text about sections.",
        url="https://example.com/",
    )
    assert q.status in ("non_article", "boilerplate_only", "summary_only", "partial")


def test_empty():
    q = assess_fulltext_quality(title="", body="", summary="", url="")
    assert q.status == "empty"
    assert q.text_chars == 0


def test_summary_only():
    q = assess_fulltext_quality(
        title="T",
        body="",
        summary="This is a reasonably long summary that exceeds the fifty character minimum threshold.",
        url="https://example.com/news/t",
    )
    assert q.status == "summary_only"


def test_to_metadata_shape():
    q = assess_fulltext_quality(title="X", body="short", summary="", url="https://e.com/news/x")
    meta = q.to_metadata()
    assert "fulltext_status" in meta
    assert meta["fulltext_status"] == q.coarse_status()
    assert meta["fulltext_quality_status"] == q.status
    assert "fulltext_reason" in meta
    assert "text_chars" in meta
