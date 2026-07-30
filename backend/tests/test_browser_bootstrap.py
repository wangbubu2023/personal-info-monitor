"""Regression tests for manual browser bootstrap completion semantics."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.platform.browser.bootstrap import run_browser_bootstrap


class _FakePage:
    url = "https://x.com/home"

    def __init__(self) -> None:
        self.closed = False

    def on(self, event: str, callback) -> None:
        if event == "close":
            raise AssertionError("closing one page must not complete the browser session")

    def is_closed(self) -> bool:
        return self.closed

    async def goto(self, *args, **kwargs) -> None:
        return None

    async def title(self) -> str:
        return "Home / X"


class _FakeContext:
    def __init__(self) -> None:
        self.pages = [_FakePage(), _FakePage()]
        self._close_callback = None
        self.close = AsyncMock(side_effect=self._emit_close)

    def on(self, event: str, callback) -> None:
        if event == "close":
            self._close_callback = callback
            asyncio.get_running_loop().call_soon(callback)

    async def cookies(self):
        return [
            {"name": "auth_token", "value": "auth", "domain": ".x.com"},
            {"name": "ct0", "value": "ct0", "domain": ".x.com"},
        ]

    async def _emit_close(self) -> None:
        if self._close_callback:
            self._close_callback()


class _AsyncPlaywright:
    def __init__(self, context: _FakeContext) -> None:
        launch = AsyncMock(return_value=context)
        self._runtime = SimpleNamespace(
            chromium=SimpleNamespace(launch_persistent_context=launch),
        )

    async def __aenter__(self):
        return self._runtime

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


@pytest.mark.asyncio
async def test_headful_bootstrap_does_not_subscribe_to_individual_page_close(tmp_path):
    context = _FakeContext()
    with patch(
        "app.platform.browser.bootstrap.async_playwright",
        return_value=_AsyncPlaywright(context),
    ), patch(
        "app.platform.browser.bootstrap.is_patchright_active",
        return_value=True,
    ), patch(
        "app.platform.browser.bootstrap._browser_default_channel",
        return_value=None,
    ):
        result = await run_browser_bootstrap(
            user_data_dir=str(tmp_path / "profile"),
            site_url="https://x.com",
            site_host="x.com",
            cookies={},
            headless=False,
            dwell_seconds=30,
        )

    assert result["cookie_count"] == 2
    assert context.close.await_count == 1
