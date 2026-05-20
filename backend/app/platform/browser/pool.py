"""Shared headless browser / Playwright pool for concurrency control.

The pool keeps one Playwright driver + one Chromium Browser process alive for
the lifetime of the app and hands out disposable BrowserContexts to each
caller. Before P2 every fetch had to spin up a fresh Playwright driver and
Chromium process (~1s cold start per call), which dominated fetch latency on
Playwright-heavy sources. Persistent-context callers (with ``user_data_dir``)
still get their own Browser because a user profile is a per-process lock.
"""

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, Optional

from app.features import PlaywrightDisabledError, playwright_enabled
from app.platform.observability.logger import get_logger

# Routed through the playwright_runtime shim so we can transparently swap in
# ``patchright`` (the bot-fingerprint-patched fork) without touching every
# call site. Tests still monkeypatch ``async_playwright`` on this module.
try:  # pragma: no cover - import wiring
    from app.platform.browser.playwright_runtime import async_playwright  # type: ignore[assignment]
    from app.platform.browser.playwright_runtime import (
        default_channel as _runtime_default_channel,
        is_patchright_active as _is_patchright_active,
        recommended_launch_args as _recommended_launch_args,
    )
except ImportError:  # pragma: no cover - dev environments without playwright installed
    async_playwright = None  # type: ignore[assignment]

    def _runtime_default_channel(explicit: Optional[str] = None) -> Optional[str]:
        return (explicit or os.environ.get("PIM_PLAYWRIGHT_CHANNEL") or "").strip() or None

    def _is_patchright_active() -> bool:
        return False

    def _recommended_launch_args(base_args: Optional[list] = None) -> list:
        return list(base_args or [])

logger = get_logger(__name__)

# Max total playwright instances operating concurrently to prevent OOM
MAX_CONCURRENT_BROWSERS = 2
_browser_semaphore = asyncio.Semaphore(MAX_CONCURRENT_BROWSERS)

# Chromium persistent-context locks the user_data_dir at the OS level
# (ProcessSingleton). Launching multiple persistent contexts on the same
# profile path concurrently fails with "profile is already in use". Serialize
# per-profile-path to keep per-site parallel fetches from colliding while
# different profiles can still run in parallel (bounded by the semaphore).
_profile_locks: Dict[str, asyncio.Lock] = {}
_profile_locks_guard: asyncio.Lock = asyncio.Lock()


async def _acquire_profile_lock(user_data_dir: str) -> asyncio.Lock:
    key = str(Path(user_data_dir).expanduser().resolve(strict=False))
    async with _profile_locks_guard:
        lock = _profile_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _profile_locks[key] = lock
    return lock


_VALID_WAIT_UNTIL = frozenset({"commit", "domcontentloaded", "load", "networkidle"})

# Process-level ephemeral-browser pool state. Protected by ``_pool_lock``;
# ``_cached_launch_key`` fingerprints the kwargs we launched with so we can
# detect mismatches (e.g. a caller requests headless=False while the cached
# browser is headless) and rebuild transparently.
_pool_lock: asyncio.Lock = asyncio.Lock()
_shared_playwright: Any = None
_shared_playwright_cm: Any = None
_shared_browser: Any = None
_cached_launch_key: Optional[tuple] = None


def _launch_key(headless: bool, channel: Optional[str]) -> tuple:
    return (bool(headless), channel or "")


async def _ensure_shared_browser(headless: bool, channel: Optional[str]):
    """Return a shared Chromium Browser, launching it lazily on first use.

    Re-launches when the previous browser is disconnected (driver crash) or
    when the requested launch parameters changed since the last call.
    """
    global _shared_playwright, _shared_playwright_cm, _shared_browser, _cached_launch_key

    if async_playwright is None:  # pragma: no cover - playwright isn't installed
        raise RuntimeError("playwright is not installed; cannot build shared browser")

    key = _launch_key(headless, channel)

    async with _pool_lock:
        browser_dead = _shared_browser is not None and not _shared_browser.is_connected()
        key_mismatch = _cached_launch_key is not None and _cached_launch_key != key
        if browser_dead or key_mismatch or _shared_browser is None:
            await _teardown_pool_locked()

            common_launch: Dict[str, Any] = {
                "headless": headless,
                "args": _recommended_launch_args([]),
            }
            if channel:
                common_launch["channel"] = channel

            cm = async_playwright()
            pw = await cm.__aenter__()
            try:
                browser = await pw.chromium.launch(**common_launch)
            except Exception:
                await cm.__aexit__(None, None, None)
                raise

            _shared_playwright_cm = cm
            _shared_playwright = pw
            _shared_browser = browser
            _cached_launch_key = key
            logger.info(
                "Playwright shared browser launched (headless=%s, channel=%s)",
                headless,
                channel or "default",
            )

        return _shared_browser


async def _teardown_pool_locked() -> None:
    """Close any cached Playwright / Browser state. Caller owns ``_pool_lock``."""
    global _shared_playwright, _shared_playwright_cm, _shared_browser, _cached_launch_key

    browser = _shared_browser
    pw_cm = _shared_playwright_cm

    _shared_browser = None
    _shared_playwright = None
    _shared_playwright_cm = None
    _cached_launch_key = None

    if browser is not None:
        try:
            await browser.close()
        except Exception as exc:  # noqa: BLE001 - teardown path must never fail caller
            logger.warning("Shared browser close failed: %s", exc)
    if pw_cm is not None:
        try:
            await pw_cm.__aexit__(None, None, None)
        except Exception as exc:  # noqa: BLE001 - teardown path must never fail caller
            logger.warning("Shared playwright exit failed: %s", exc)


async def shutdown_browser_pool() -> None:
    """Close the shared Playwright driver and Chromium process.

    Safe to call multiple times. Invoked from the FastAPI lifespan shutdown so
    that uvicorn graceful-stop leaves no orphan Chromium children.
    """
    async with _pool_lock:
        await _teardown_pool_locked()
    logger.info("Playwright shared browser pool shut down")


def local_playwright_fetch_prefs(metadata: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Resolve Playwright navigation / timing prefs from source metadata (local-first, js-eyes-style control).

    Keys (all optional):
    - playwright_wait_until: commit | domcontentloaded | load | networkidle
    - playwright_fallback_wait_until: used when primary goto times out (default domcontentloaded)
    - playwright_goto_timeout_ms: 5_000–180_000
    - playwright_post_goto_wait_ms: extra settle time after navigation (0–60_000)
    - playwright_scroll_lazy: if true, scroll to bottom before reading DOM (lazy sections)
    - playwright_headless: default true; set false for local headed debugging (paywalls / bot checks)
    - playwright_viewport_width / playwright_viewport_height: set both to apply viewport
    - playwright_locale: e.g. en-US
    - playwright_extra_http_headers: dict merged into page.set_extra_http_headers (first page only)
    """
    m = metadata if isinstance(metadata, dict) else {}
    wait_until = str(m.get("playwright_wait_until") or "networkidle").strip().lower()
    if wait_until not in _VALID_WAIT_UNTIL:
        wait_until = "networkidle"
    fb = str(m.get("playwright_fallback_wait_until") or "domcontentloaded").strip().lower()
    if fb not in _VALID_WAIT_UNTIL:
        fb = "domcontentloaded"
    goto_timeout = int(m.get("playwright_goto_timeout_ms") or 60000)
    goto_timeout = max(5000, min(180_000, goto_timeout))
    post_wait = int(m.get("playwright_post_goto_wait_ms") if m.get("playwright_post_goto_wait_ms") is not None else 3500)
    post_wait = max(0, min(60_000, post_wait))
    scroll_lazy = bool(m.get("playwright_scroll_lazy"))
    headless = m.get("playwright_headless")
    if headless is None:
        headless = True
    else:
        headless = bool(headless)
    vw = m.get("playwright_viewport_width")
    vh = m.get("playwright_viewport_height")
    viewport = None
    if vw is not None and vh is not None:
        try:
            viewport = {"width": int(vw), "height": int(vh)}
        except (TypeError, ValueError):
            viewport = None
    locale = m.get("playwright_locale")
    if locale is not None:
        locale = str(locale).strip() or None
    extra_headers = m.get("playwright_extra_http_headers")
    if not isinstance(extra_headers, dict):
        extra_headers = None
    return {
        "wait_until": wait_until,
        "fallback_wait_until": fb,
        "goto_timeout_ms": goto_timeout,
        "post_goto_wait_ms": post_wait,
        "scroll_lazy": scroll_lazy,
        "headless": headless,
        "viewport": viewport,
        "locale": locale,
        "extra_http_headers": extra_headers,
    }


def _resolve_playwright_channel(explicit_channel: Optional[str]) -> Optional[str]:
    return _runtime_default_channel(explicit_channel)


@asynccontextmanager
async def get_browser_context(
    headless: bool = True,
    user_data_dir: str = None,
    user_agent: str = None,
    storage_state: Optional[str] = None,
    viewport: Optional[Dict[str, int]] = None,
    locale: Optional[str] = None,
    channel: Optional[str] = None,
) -> AsyncGenerator:
    """Acquire a managed browser context under global concurrency limit.

    When ``user_data_dir`` is set, launches a persistent Chromium profile (session fidelity).
    Otherwise launches ephemeral Chromium; optional ``storage_state`` loads cookies/localStorage
    from a Playwright export JSON (path must exist). Do not pass ``storage_state`` together with
    ``user_data_dir`` — the on-disk profile is authoritative.
    """
    if not playwright_enabled():
        # Single chokepoint so every collector / cookie path gets the same
        # typed error when the master flag is off, instead of failing deep in
        # Playwright's import stack.
        raise PlaywrightDisabledError(
            "Playwright is disabled by PIM_FEATURE_PLAYWRIGHT=false; browser-based fetch is unavailable."
        )

    resolved_channel = _resolve_playwright_channel(channel)
    if user_data_dir and storage_state:
        logger.debug("Ignoring storage_state while user_data_dir is set (persistent profile wins)")

    # Chromium's launch_persistent_context holds an OS-level lock on the
    # user_data_dir (ProcessSingleton). Concurrent launches on the same dir
    # fail with "profile is already in use"; serialize per-dir so same-profile
    # fetches queue up while different profiles still run in parallel.
    profile_lock = await _acquire_profile_lock(user_data_dir) if user_data_dir else None

    @asynccontextmanager
    async def _maybe_profile_lock():
        if profile_lock is None:
            yield
            return
        async with profile_lock:
            yield

    async with _maybe_profile_lock():
        async with _browser_semaphore:
            logger.debug("Acquired browser semaphore slot")

            if user_data_dir:
                # Persistent profiles lock the user-data-dir at the process level,
                # so they must stay on the legacy per-call launch path.
                common_launch: Dict[str, Any] = {
                    "headless": headless,
                    "args": _recommended_launch_args([]),
                }
                if resolved_channel:
                    common_launch["channel"] = resolved_channel

                async with async_playwright() as p:
                    try:
                        ctx_kwargs = {
                            **common_launch,
                            "user_data_dir": user_data_dir,
                        }
                        # Patchright + chrome channel works best when we let the
                        # browser pick its own UA + viewport (the patched fork
                        # already rotates plausible ones and any override trips an
                        # easy fingerprint mismatch on the server side).
                        if user_agent and not _is_patchright_active():
                            ctx_kwargs["user_agent"] = user_agent
                        if viewport and not _is_patchright_active():
                            ctx_kwargs["viewport"] = viewport
                        elif _is_patchright_active():
                            ctx_kwargs["no_viewport"] = True
                        if locale:
                            ctx_kwargs["locale"] = locale
                        context = await p.chromium.launch_persistent_context(**ctx_kwargs)
                    except Exception as e:
                        logger.error(f"Failed to launch persistent context: {e}")
                        raise
                    try:
                        yield context
                    finally:
                        await context.close()
                return

            # Ephemeral contexts share a single Browser process across the app.
            browser = await _ensure_shared_browser(headless=headless, channel=resolved_channel)
            ctx_args: Dict[str, Any] = {}
            if user_agent:
                ctx_args["user_agent"] = user_agent
            if viewport:
                ctx_args["viewport"] = viewport
            if locale:
                ctx_args["locale"] = locale
            state_path = (storage_state or "").strip()
            if state_path and Path(state_path).is_file():
                ctx_args["storage_state"] = state_path
            elif state_path:
                logger.warning("Playwright storage_state path missing or not a file: %s", state_path)

            try:
                context = await browser.new_context(**ctx_args)
            except Exception as exc:  # noqa: BLE001 - playwright exposes opaque browser errors
                # Browser might have died between is_connected() and new_context();
                # force-rebuild once and retry.
                logger.warning("Shared browser rejected new_context (%s); rebuilding", exc)
                async with _pool_lock:
                    await _teardown_pool_locked()
                browser = await _ensure_shared_browser(headless=headless, channel=resolved_channel)
                context = await browser.new_context(**ctx_args)

            try:
                yield context
            finally:
                try:
                    await context.close()
                except Exception as exc:  # noqa: BLE001 - teardown path must never fail caller
                    logger.debug("Context close raised %s", exc)
