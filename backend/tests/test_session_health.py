"""Tests for browser-session health classification."""

from __future__ import annotations

from app.domains.fetch.session_health import classify_session_health


def test_ok_session():
    h = classify_session_health(
        check_url="https://example.com/dashboard",
        final_url="https://example.com/dashboard",
        html="<html><body>Welcome back, your feed is here with lots of content.</body></html>",
    )
    assert h.status == "ok"
    assert h.reason == "ok"
    assert h.suggested_action == "none"


def test_redirect_to_login():
    h = classify_session_health(
        check_url="https://example.com/dashboard",
        final_url="https://example.com/login?next=/dashboard",
        html="<html><body>login</body></html>",
    )
    assert h.status == "error"
    assert h.reason == "login_required"
    assert h.suggested_action == "relogin"


def test_bot_wall():
    h = classify_session_health(
        check_url="https://example.com/x",
        final_url="https://example.com/x",
        html="<html><body>Access denied. Checking your browser. Cloudflare.</body></html>",
    )
    assert h.reason == "bot_wall"
    assert h.suggested_action == "switch_rss_only"


def test_captcha():
    h = classify_session_health(
        check_url="https://example.com/x",
        final_url="https://example.com/x",
        html="<html><body>Please complete the captcha to verify you are human</body></html>",
    )
    assert h.reason == "captcha"


def test_inpage_login_with_cookies_is_expired():
    h = classify_session_health(
        check_url="https://example.com/x",
        final_url="https://example.com/x",
        html="<html><body>Please sign in to view this page</body></html>",
        cookie_count=5,
    )
    assert h.reason == "expired"
    assert h.suggested_action == "relogin"


def test_inpage_login_without_cookies_is_login_required():
    h = classify_session_health(
        check_url="https://example.com/x",
        final_url="https://example.com/x",
        html="<html><body>Please log in to continue</body></html>",
        cookie_count=0,
    )
    assert h.reason == "login_required"


def test_selector_missing_warning():
    h = classify_session_health(
        check_url="https://example.com/x",
        final_url="https://example.com/x",
        html="<html><body>" + ("normal content " * 500) + "</body></html>",
        required_selectors_present=[False, False],
    )
    assert h.status == "warning"
    assert h.reason == "selector_missing"
    assert h.suggested_action == "retry_later"


def test_selector_present_is_ok():
    h = classify_session_health(
        check_url="https://example.com/x",
        final_url="https://example.com/x",
        html="<html><body>" + ("normal content " * 500) + "</body></html>",
        required_selectors_present=[False, True],
    )
    assert h.status == "ok"


def test_to_dict_shape():
    h = classify_session_health(
        check_url="https://example.com/x",
        final_url="https://example.com/login",
        html="login",
        validated_at="2026-06-01T12:00:00Z",
    )
    d = h.to_dict()
    assert d["status"] == "error"
    assert d["reason"] == "login_required"
    assert d["validated_at"] == "2026-06-01T12:00:00Z"
