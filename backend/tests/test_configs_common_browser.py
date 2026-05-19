"""Unit tests for ``app.api.configs_common_browser`` URL / validation helpers."""

from __future__ import annotations

from app.api.configs_common_browser import (
    browser_validation_probe_url,
    _validation_html_for_wall_scan,
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
