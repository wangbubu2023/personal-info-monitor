"""Tests for app.platform.browser.pool — local Playwright fetch prefs (metadata-driven).

Phase 5 step 7 relocated the browser-pool implementation from
``app.utils.browser`` to ``app.platform.browser.pool``. The ``async_playwright``
binding the production code actually reads from lives on the canonical
module, so ``patch.object`` must target the canonical module — patching the
``app.utils.browser`` re-export shim is a no-op for binding-resolution
purposes (the shim re-exports references; rebinding a shim attribute does
not affect the canonical caller's local lookup).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.platform.browser import pool as browser_module
from app.platform.browser.pool import (
    get_browser_context,
    local_playwright_fetch_prefs,
    shutdown_browser_pool,
)


class TestLocalPlaywrightFetchPrefs:

    def test_defaults(self):
        p = local_playwright_fetch_prefs({})
        assert p["wait_until"] == "networkidle"
        assert p["fallback_wait_until"] == "domcontentloaded"
        assert p["goto_timeout_ms"] == 60000
        assert p["post_goto_wait_ms"] == 3500
        assert p["scroll_lazy"] is False
        assert p["headless"] is True
        assert p["viewport"] is None
        assert p["locale"] is None
        assert p["extra_http_headers"] is None

    def test_none_metadata(self):
        p = local_playwright_fetch_prefs(None)
        assert p["wait_until"] == "networkidle"

    def test_invalid_wait_until_reverts(self):
        p = local_playwright_fetch_prefs({"playwright_wait_until": "not-a-mode"})
        assert p["wait_until"] == "networkidle"

    def test_domcontentloaded_and_timeouts_clamped(self):
        p = local_playwright_fetch_prefs(
            {
                "playwright_wait_until": "domcontentloaded",
                "playwright_goto_timeout_ms": 999999,
                "playwright_post_goto_wait_ms": 999999,
            }
        )
        assert p["wait_until"] == "domcontentloaded"
        assert p["goto_timeout_ms"] == 180_000
        assert p["post_goto_wait_ms"] == 60_000

    def test_goto_timeout_minimum(self):
        p = local_playwright_fetch_prefs({"playwright_goto_timeout_ms": 100})
        assert p["goto_timeout_ms"] == 5000

    def test_headless_false(self):
        p = local_playwright_fetch_prefs({"playwright_headless": False})
        assert p["headless"] is False

    def test_viewport(self):
        p = local_playwright_fetch_prefs(
            {"playwright_viewport_width": 1280, "playwright_viewport_height": 720}
        )
        assert p["viewport"] == {"width": 1280, "height": 720}

    def test_viewport_partial_ignored(self):
        p = local_playwright_fetch_prefs({"playwright_viewport_width": 1280})
        assert p["viewport"] is None

    def test_locale_trim(self):
        p = local_playwright_fetch_prefs({"playwright_locale": "  zh-CN  "})
        assert p["locale"] == "zh-CN"

    def test_extra_headers_non_dict_ignored(self):
        p = local_playwright_fetch_prefs({"playwright_extra_http_headers": "nope"})
        assert p["extra_http_headers"] is None

    def test_extra_headers_kept(self):
        p = local_playwright_fetch_prefs(
            {"playwright_extra_http_headers": {"X-Debug": "1"}}
        )
        assert p["extra_http_headers"] == {"X-Debug": "1"}


class _FakeBrowser:
    """Minimal stand-in for playwright.async_api.Browser used by the pool tests."""

    def __init__(self) -> None:
        self.new_context = AsyncMock(side_effect=self._new_context)
        self.close = AsyncMock()
        self.new_context_calls: list[dict] = []
        self._connected = True

    def is_connected(self) -> bool:
        return self._connected

    async def _new_context(self, **kwargs):
        self.new_context_calls.append(kwargs)
        context = MagicMock()
        context.close = AsyncMock()
        return context


class _FakePlaywright:
    """Stand-in for async_playwright() context manager."""

    def __init__(self, browser: _FakeBrowser) -> None:
        self._browser = browser
        self.chromium = MagicMock()
        self.chromium.launch = AsyncMock(return_value=self._browser)
        self.exit_called = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.exit_called += 1
        return False


@pytest.fixture
async def _reset_browser_pool():
    """Make sure each test starts with a clean pool and leaves one too."""
    await shutdown_browser_pool()
    yield
    await shutdown_browser_pool()


class TestSharedBrowserPool:

    @pytest.mark.asyncio
    async def test_ephemeral_contexts_reuse_single_browser(self, _reset_browser_pool):
        """Two get_browser_context() calls must hit browser.new_context(), not launch()."""
        fake_browser = _FakeBrowser()
        fake_pw = _FakePlaywright(fake_browser)

        with patch.object(browser_module, "async_playwright", return_value=fake_pw):
            async with get_browser_context(headless=True) as ctx_a:
                assert ctx_a is not None
            async with get_browser_context(headless=True) as ctx_b:
                assert ctx_b is not None

        assert fake_pw.chromium.launch.await_count == 1, \
            "Shared pool must launch Chromium once across two ephemeral calls"
        assert fake_browser.new_context.await_count == 2

    @pytest.mark.asyncio
    async def test_shutdown_closes_shared_browser(self, _reset_browser_pool):
        fake_browser = _FakeBrowser()
        fake_pw = _FakePlaywright(fake_browser)

        with patch.object(browser_module, "async_playwright", return_value=fake_pw):
            async with get_browser_context(headless=True):
                pass
            await shutdown_browser_pool()

        fake_browser.close.assert_awaited()
        assert fake_pw.exit_called >= 1

    @pytest.mark.asyncio
    async def test_rebuilds_after_disconnect(self, _reset_browser_pool):
        """A dead Chromium child must trigger a transparent relaunch."""
        first_browser = _FakeBrowser()
        second_browser = _FakeBrowser()
        first_pw = _FakePlaywright(first_browser)
        second_pw = _FakePlaywright(second_browser)
        sequence = [first_pw, second_pw]

        def factory():
            return sequence.pop(0)

        with patch.object(browser_module, "async_playwright", side_effect=factory):
            async with get_browser_context(headless=True):
                pass
            # Simulate a driver crash between requests.
            first_browser._connected = False
            async with get_browser_context(headless=True):
                pass

        assert first_pw.chromium.launch.await_count == 1
        assert second_pw.chromium.launch.await_count == 1


class TestPersistentProfileSerialization:
    """Chromium's persistent profile holds an OS-level ProcessSingleton lock on
    the user_data_dir; concurrent launches on the same dir blow up with
    "profile is already in use". get_browser_context must serialize them."""

    @pytest.mark.asyncio
    async def test_same_profile_calls_run_serially(self, tmp_path, _reset_browser_pool):
        import asyncio

        profile = str(tmp_path / "prof")
        in_flight = 0
        max_in_flight = 0

        class _SlowContext:
            close = AsyncMock()

        async def _launch_persistent_context(**_kwargs):
            nonlocal in_flight, max_in_flight
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0.05)
            in_flight -= 1
            return _SlowContext()

        class _PW:
            def __init__(self):
                self.chromium = MagicMock()
                self.chromium.launch_persistent_context = AsyncMock(
                    side_effect=_launch_persistent_context
                )

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

        with patch.object(browser_module, "async_playwright", side_effect=lambda: _PW()):
            async def _run():
                async with get_browser_context(user_data_dir=profile):
                    await asyncio.sleep(0.01)

            await asyncio.gather(*(_run() for _ in range(4)))

        assert max_in_flight == 1, (
            f"persistent context launches on the same profile must be serialized, "
            f"observed concurrency {max_in_flight}"
        )

    @pytest.mark.asyncio
    async def test_different_profiles_can_run_in_parallel(self, tmp_path, _reset_browser_pool):
        import asyncio

        prof_a = str(tmp_path / "a")
        prof_b = str(tmp_path / "b")
        active_per_dir: dict[str, int] = {}
        observed: list[int] = []

        class _SlowContext:
            close = AsyncMock()

        async def _launch_persistent_context(*, user_data_dir, **_kwargs):
            active_per_dir[user_data_dir] = active_per_dir.get(user_data_dir, 0) + 1
            observed.append(sum(active_per_dir.values()))
            await asyncio.sleep(0.05)
            active_per_dir[user_data_dir] -= 1
            return _SlowContext()

        class _PW:
            def __init__(self):
                self.chromium = MagicMock()
                self.chromium.launch_persistent_context = AsyncMock(
                    side_effect=_launch_persistent_context
                )

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

        with patch.object(browser_module, "async_playwright", side_effect=lambda: _PW()):
            async def _run(p):
                async with get_browser_context(user_data_dir=p):
                    await asyncio.sleep(0.01)

            await asyncio.gather(_run(prof_a), _run(prof_b))

        assert max(observed) >= 2, "different profiles should be allowed to launch in parallel"
