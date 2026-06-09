"""Tests for shared Playwright runtime defaults."""

from __future__ import annotations

from app.platform.browser import playwright_runtime as runtime


def test_patchright_default_channel_uses_bundled_chromium(monkeypatch):
    monkeypatch.delenv("PIM_PLAYWRIGHT_CHANNEL", raising=False)
    monkeypatch.setattr(runtime, "backend_name", lambda: "patchright")

    assert runtime.default_channel() is None


def test_channel_env_still_allows_real_chrome_opt_in(monkeypatch):
    monkeypatch.setenv("PIM_PLAYWRIGHT_CHANNEL", "chrome")

    assert runtime.default_channel() == "chrome"


def test_channel_none_env_uses_bundled_chromium(monkeypatch):
    monkeypatch.setenv("PIM_PLAYWRIGHT_CHANNEL", "none")

    assert runtime.default_channel() is None


def test_no_sandbox_always_adds_flags(monkeypatch):
    monkeypatch.setenv("PIM_PLAYWRIGHT_NO_SANDBOX", "always")
    monkeypatch.setattr(runtime, "backend_name", lambda: "playwright")

    args = runtime.recommended_launch_args([])

    assert "--no-sandbox" in args
    assert "--disable-setuid-sandbox" in args
    assert "--disable-blink-features=AutomationControlled" in args


def test_no_sandbox_never_suppresses_auto_flags(monkeypatch):
    monkeypatch.setenv("PIM_PLAYWRIGHT_NO_SANDBOX", "never")
    monkeypatch.setattr(runtime, "backend_name", lambda: "playwright")
    monkeypatch.setattr(runtime, "_running_in_container", lambda: True)
    monkeypatch.setattr(runtime, "_root_or_userns_restricted", lambda: True)

    args = runtime.recommended_launch_args([])

    assert "--no-sandbox" not in args
    assert "--disable-setuid-sandbox" not in args


def test_no_sandbox_auto_detects_container(monkeypatch):
    monkeypatch.delenv("PIM_PLAYWRIGHT_NO_SANDBOX", raising=False)
    monkeypatch.setattr(runtime, "backend_name", lambda: "playwright")
    monkeypatch.setattr(runtime, "_running_in_container", lambda: True)
    monkeypatch.setattr(runtime, "_root_or_userns_restricted", lambda: False)

    args = runtime.recommended_launch_args([])

    assert "--no-sandbox" in args
    assert "--disable-setuid-sandbox" in args


def test_patchright_strips_blink_flag_but_keeps_sandbox_flags(monkeypatch):
    monkeypatch.setenv("PIM_PLAYWRIGHT_NO_SANDBOX", "always")
    monkeypatch.setattr(runtime, "backend_name", lambda: "patchright")

    args = runtime.recommended_launch_args(
        ["--disable-blink-features=AutomationControlled"]
    )

    assert not any("blink-features=AutomationControlled" in arg for arg in args)
    assert "--no-sandbox" in args
    assert "--disable-setuid-sandbox" in args
