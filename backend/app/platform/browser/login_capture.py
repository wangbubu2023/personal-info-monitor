"""Headless Playwright login flow that captures the post-login cookie jar.

Tries a small ranked list of common username/password/submit selectors first;
falls back to caller-supplied selectors when present. After submitting the
form we either wait for an explicit ``success_selector`` or for the page to
reach ``networkidle``, then return cookies whose domain matches the supplied
``site_url``.

This module owns *no* business decisions about whether a site requires login,
which credentials to use, or what to do with the resulting cookies — those
live in ``app.domains.fetch.auth.refresh``.
"""

from __future__ import annotations

from app.platform.auth.cookies import domain_match
from app.platform.observability.logger import get_logger
from app.utils.url import normalize_host

logger = get_logger(__name__)

_DEFAULT_USERNAME_SELECTORS = [
    'input[name="username"]',
    'input[name="email"]',
    'input[type="email"]',
    '#username',
    '#email',
    'input[id*="user" i]',
    'input[id*="email" i]',
]

_DEFAULT_PASSWORD_SELECTORS = [
    'input[name="password"]',
    'input[type="password"]',
    '#password',
    'input[id*="pass" i]',
]

_DEFAULT_SUBMIT_SELECTORS = [
    'button[type="submit"]',
    'input[type="submit"]',
    'button[name="sign-in"]',
    'button[id*="sign" i]',
    'button[id*="login" i]',
    'button[class*="sign" i]',
    'button[class*="login" i]',
]


async def _find_first_selector(page, candidates):
    for selector in candidates:
        if not selector:
            continue
        try:
            if await page.locator(selector).count() > 0:
                return selector
        except Exception as exc:  # noqa: BLE001 - Playwright raises various errors per selector
            logger.debug("Selector probe failed for '%s': %s", selector, exc)
            continue
    return None


async def _page_has_captcha(page) -> bool:
    try:
        html = (await page.content()).lower()
    except Exception as exc:  # noqa: BLE001 - Playwright page may be transient/closed
        logger.debug("Failed to inspect page content for captcha markers: %s", exc)
        html = ""
    captcha_markers = [
        "captcha",
        "verify you are human",
        "are you human",
        "bot challenge",
        "security challenge",
    ]
    if any(marker in html for marker in captcha_markers):
        return True

    try:
        frame_urls = [(f.url or "").lower() for f in page.frames]
    except Exception as exc:  # noqa: BLE001 - frame list may be transient/closed
        logger.debug("Failed to inspect frame URLs for captcha markers: %s", exc)
        frame_urls = []
    return any(("captcha" in u) or ("challenge" in u) for u in frame_urls)


async def login_and_capture_cookies(
    site_url: str,
    login_url: str,
    username: str,
    password: str,
    login_selectors: dict | None = None,
) -> dict:
    """Drive Playwright through a login form and return matching cookies.

    Raises:
        PlaywrightDisabledError: when ``PIM_FEATURE_PLAYWRIGHT`` is off.
        RuntimeError: on form-not-found, captcha, or login-flow errors.
    """

    from app.features import PlaywrightDisabledError, playwright_enabled
    from app.platform.browser.playwright_runtime import async_playwright

    if not playwright_enabled():
        raise PlaywrightDisabledError(
            "Automated login flow requires Playwright (PIM_FEATURE_PLAYWRIGHT=true)."
        )

    selectors = login_selectors or {}
    username_candidates = [selectors.get("username")] + _DEFAULT_USERNAME_SELECTORS
    password_candidates = [selectors.get("password")] + _DEFAULT_PASSWORD_SELECTORS
    submit_candidates = [selectors.get("submit")] + _DEFAULT_SUBMIT_SELECTORS
    success_selector = selectors.get("success")

    site_host = normalize_host(site_url)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context()
            try:
                page = await context.new_page()
                await page.goto(login_url, wait_until="domcontentloaded", timeout=60000)

                user_selector = await _find_first_selector(page, username_candidates)
                pass_selector = await _find_first_selector(page, password_candidates)
                if not user_selector or not pass_selector:
                    if await _page_has_captcha(page):
                        raise RuntimeError("Captcha challenge detected on login page")
                    raise RuntimeError("Login form not found")

                await page.fill(user_selector, username)
                await page.fill(pass_selector, password)

                submit_selector = await _find_first_selector(page, submit_candidates)
                if submit_selector:
                    await page.click(submit_selector)
                else:
                    await page.press(pass_selector, "Enter")

                if success_selector:
                    try:
                        await page.wait_for_selector(success_selector, timeout=30000)
                    except Exception as exc:  # noqa: BLE001 - selector wait may raise per-driver errors
                        logger.debug(
                            "Success selector wait failed, fallback to networkidle: %s",
                            exc,
                        )
                        await page.wait_for_load_state("networkidle", timeout=30000)
                else:
                    await page.wait_for_load_state("networkidle", timeout=30000)

                cookie_items = await context.cookies()
                if not cookie_items:
                    return {}

                cookie_dict = {}
                for c in cookie_items:
                    name = c.get("name")
                    value = c.get("value")
                    domain = c.get("domain") or ""
                    if not name or value is None:
                        continue
                    if domain_match(domain, site_host):
                        cookie_dict[str(name)] = str(value)
                return cookie_dict
            finally:
                try:
                    await context.close()
                except Exception as exc:  # noqa: BLE001 - Playwright close may raise transient errors
                    logger.debug("Failed to close login context for %s: %s", site_url, exc)
        finally:
            try:
                await browser.close()
            except Exception as exc:  # noqa: BLE001 - Playwright close may raise transient errors
                logger.debug("Failed to close login browser for %s: %s", site_url, exc)
