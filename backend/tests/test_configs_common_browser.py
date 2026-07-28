"""Unit tests for ``app.api.configs_common_browser`` URL / validation helpers."""

from __future__ import annotations

from app.api.configs_common_browser import (
    _has_wsj_authenticated_session,
    browser_validation_probe_url,
    is_wsj_host,
    _validation_html_for_wall_scan,
    _wsj_auth_cookie_names,
)


class TestBrowserValidationProbeUrl:

    def test_explicit_test_url_wins(self):
        assert (
            browser_validation_probe_url(
                "https://www.economist.com",
                "https://example.com/article",
            )
            == "https://example.com/article"
        )

    def test_economist_root_to_international(self):
        assert browser_validation_probe_url("https://www.economist.com/", None) == (
            "https://www.economist.com/international"
        )
        assert browser_validation_probe_url("https://www.economist.com", None) == (
            "https://www.economist.com/international"
        )

    def test_economist_section_unchanged(self):
        assert browser_validation_probe_url("https://www.economist.com/china", None) == (
            "https://www.economist.com/china"
        )

    def test_other_site_unchanged(self):
        assert browser_validation_probe_url("https://www.ft.com/", None) == "https://www.ft.com/"


class TestValidationHtmlForWallScan:

    def test_strips_script_before_substring_scan(self):
        raw = '<html><body><script>var x = "enable javascript please";</script><p>ok</p></body></html>'
        cleaned = _validation_html_for_wall_scan(raw)
        assert "enable javascript" not in cleaned
        assert "<p>ok</p>" in cleaned


class TestWsjSessionCookies:

    def test_recognizes_wsj_subdomains(self):
        assert is_wsj_host("https://www.wsj.com/")
        assert is_wsj_host("https://cn.wsj.com/")
        assert not is_wsj_host("https://notwsj.com/")

    def test_accepts_wsj_session_plus_dow_jones_sso(self):
        cookies = [
            {"name": "DJSESSION", "domain": ".wsj.com"},
            {"name": "sso", "domain": ".dowjones.com"},
            {"name": "session", "domain": "sso.accounts.dowjones.com"},
            {"name": "datadome", "domain": ".wsj.com"},
        ]

        assert _wsj_auth_cookie_names(cookies) == {"djsession", "sso", "session"}
        assert _has_wsj_authenticated_session(cookies)

    def test_rejects_public_tracking_cookie_jar(self):
        cookies = [
            {"name": "datadome", "domain": ".wsj.com"},
            {"name": "_ga", "domain": ".dowjones.com"},
            {"name": "DJSESSION", "domain": ".unrelated.example"},
        ]

        assert not _has_wsj_authenticated_session(cookies)

    def test_requires_both_wsj_and_sso_signals(self):
        assert not _has_wsj_authenticated_session(
            [{"name": "DJSESSION", "domain": ".wsj.com"}]
        )
        assert not _has_wsj_authenticated_session(
            [{"name": "sso", "domain": ".dowjones.com"}]
        )
