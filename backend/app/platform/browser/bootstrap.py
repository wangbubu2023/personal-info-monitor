"""Persistent-context Playwright bootstrap that captures the post-login cookie jar.

Headful mode hands the window to the user (they log in / solve captcha
themselves); headless mode drives ``dwell_seconds`` as a fixed settle wait.
Either way we return ``(final_url, title, cookie_count, cookies)`` so the API
layer can sync the captured cookies into the linked ``AuthConfig`` without an
extra validate round-trip.

Stealth handling differs between vanilla playwright and patchright:
``is_patchright_active()`` skips the JS-level stealth injection and the
hand-rolled UA, because the patched fork already covers those signals and
adding them back can *regress* the fingerprint.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any, Dict, List

from app.features import PlaywrightDisabledError, playwright_enabled
from app.utils.cookies import cookie_domains_for_host
from app.utils.logger import get_logger
from app.utils.playwright_runtime import (
    async_playwright,
    default_channel as _browser_default_channel,
    is_patchright_active,
    recommended_launch_args,
)
from app.utils.playwright_stealth import stealth_init_script

logger = get_logger(__name__)

_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _require_playwright(action: str) -> None:
    if not playwright_enabled():
        raise PlaywrightDisabledError(
            f"{action} requires Playwright (PIM_FEATURE_PLAYWRIGHT=true)."
        )


async def run_browser_bootstrap(
    *,
    user_data_dir: str,
    site_url: str,
    site_host: str,
    cookies: Dict[str, str],
    headless: bool,
    dwell_seconds: int,
) -> Dict[str, Any]:
    _require_playwright("Browser bootstrap")

    async with async_playwright() as p:
        # Patchright's guidance for Datadome/Cloudflare-class sites: launch a
        # persistent profile against the real Chrome channel, drop custom
        # launch args + UA overrides, and let the patched fork fake the
        # remaining CDP signals itself. Anything we add here tends to *hurt*
        # stealth, not help it.
        launch_kwargs: Dict[str, Any] = {
            "user_data_dir": user_data_dir,
            "headless": headless,
            "args": recommended_launch_args([]),
        }
        channel = _browser_default_channel()
        if channel:
            launch_kwargs["channel"] = channel
        if is_patchright_active():
            launch_kwargs["no_viewport"] = True
        else:
            launch_kwargs["user_agent"] = _BROWSER_USER_AGENT
        context = await p.chromium.launch_persistent_context(**launch_kwargs)
        try:
            if cookies:
                cookie_items: List[Dict[str, str]] = []
                for name, value in cookies.items():
                    if not name or value is None:
                        continue
                    for domain in cookie_domains_for_host(site_host):
                        cookie_items.append(
                            {
                                "name": str(name),
                                "value": str(value),
                                "domain": domain,
                                "path": "/",
                            }
                        )
                if cookie_items:
                    await context.add_cookies(cookie_items)

            page = context.pages[0] if context.pages else await context.new_page()
            # Patchright already patches the signals our stealth script covers,
            # and layering the JS-level overrides on top actually regresses the
            # fingerprint (navigator.plugins mismatch etc.). Only inject the
            # stealth script on the vanilla playwright path.
            if not is_patchright_active():
                await page.add_init_script(stealth_init_script())
            # News sites (NYT, WSJ, Bloomberg…) stream ads/analytics continuously,
            # so ``networkidle`` almost never fires within the timeout. Use
            # ``domcontentloaded`` — enough for the user to see the page and
            # interact (login, solve captcha). In headful mode, swallow goto
            # timeouts: the window is already visible and the user can navigate
            # manually.
            try:
                await page.goto(site_url, wait_until="domcontentloaded", timeout=45000)
            except Exception as e:  # noqa: BLE001 — headful UX should not die here
                if headless:
                    raise
                logger.warning(
                    "Initial navigation to %s did not complete cleanly (%s); "
                    "leaving window open for manual login.",
                    site_url,
                    e,
                )

            cookie_holder: Dict[str, Any] = {"cookies": []}
            if headless:
                # Headless: use dwell as a fixed "settle" wait; the user has no
                # way to close the window, so there's nothing to watch.
                if dwell_seconds > 0:
                    await page.wait_for_timeout(dwell_seconds * 1000)
            else:
                # Headful: treat ``dwell_seconds`` as the upper bound. Wait
                # until the user is visibly "done" — either the browser
                # context closes, or every page the user was using has been
                # closed. macOS Chrome (especially via Patchright's real
                # ``channel="chrome"``) likes to linger in the background
                # after the last window is closed, so the ``context.close``
                # event alone is not enough; we poll ``context.pages`` and
                # treat "no open pages" as a completion signal.
                #
                # Users often Cmd+Q / close the window immediately after
                # logging in. That tears the browser down before we can call
                # ``context.cookies()`` at the end, which used to surface as
                # "0 cookies". Keep a rolling snapshot while the session is
                # alive and fall back to it when the final read fails.

                async def _snapshot_cookies() -> None:
                    try:
                        cookie_holder["cookies"] = await context.cookies()
                    except Exception:  # noqa: BLE001 - context may be closing
                        pass

                async def _cookie_poll_loop() -> None:
                    await _snapshot_cookies()
                    try:
                        while True:
                            await asyncio.sleep(1.5)
                            await _snapshot_cookies()
                    except asyncio.CancelledError:
                        await _snapshot_cookies()
                        raise

                timeout_s = max(dwell_seconds, 30)
                close_event = asyncio.Event()
                context.on("close", lambda *_: close_event.set())
                for _pg in list(context.pages):
                    _pg.on("close", lambda *_: close_event.set())
                context.on(
                    "page",
                    lambda pg: pg.on("close", lambda *_: close_event.set()),
                )

                cookie_poll_task = asyncio.create_task(_cookie_poll_loop())

                async def _poll_until_no_pages() -> None:
                    # Give the first page a moment to finish loading so we
                    # don't mistake the brief interval before navigation for
                    # "all pages closed".
                    await asyncio.sleep(2)
                    while True:
                        await asyncio.sleep(1.5)
                        try:
                            open_pages = [
                                pg for pg in context.pages if not pg.is_closed()
                            ]
                        except Exception:  # noqa: BLE001 - context gone = done
                            return
                        if not open_pages:
                            logger.info(
                                "Headful bootstrap: no open pages left, treating as completed"
                            )
                            return

                wait_task = asyncio.create_task(close_event.wait())
                poll_task = asyncio.create_task(_poll_until_no_pages())
                try:
                    done, pending = await asyncio.wait(
                        {wait_task, poll_task},
                        timeout=timeout_s,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if not done:
                        logger.info(
                            "Headful bootstrap timed out after %ss; closing window automatically",
                            timeout_s,
                        )
                    for t in pending:
                        t.cancel()
                        with contextlib.suppress(BaseException):
                            await t
                except asyncio.TimeoutError:
                    logger.info(
                        "Headful bootstrap timed out after %ss; closing window automatically",
                        timeout_s,
                    )
                finally:
                    cookie_poll_task.cancel()
                    with contextlib.suppress(BaseException):
                        await cookie_poll_task

            try:
                cookies_now = await context.cookies()
                cookie_count = len(cookies_now)
                final_url = page.url
                title = await page.title()
            except Exception:  # noqa: BLE001 - context may already be closed by the user
                snap = cookie_holder.get("cookies") if not headless else []
                if not isinstance(snap, list):
                    snap = []
                cookies_now = snap
                cookie_count = len(cookies_now)
                final_url = site_url
                title = ""
            else:
                if not headless and not cookies_now:
                    snap = cookie_holder.get("cookies")
                    if isinstance(snap, list) and snap:
                        cookies_now = snap
                        cookie_count = len(cookies_now)
                        logger.info(
                            "Headful bootstrap: final context.cookies() empty; using last snapshot (%s)",
                            cookie_count,
                        )
            return {
                "final_url": final_url,
                "title": title,
                "cookie_count": cookie_count,
                # Full cookie list so the API layer can sync authentication
                # cookies into the linked ``AuthConfig`` without needing a
                # follow-up validate round-trip.
                "cookies": cookies_now,
            }
        finally:
            try:
                await context.close()
            except Exception:  # noqa: BLE001 - user may have already closed it
                pass
