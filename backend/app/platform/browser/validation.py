"""Validate a persistent Playwright profile against its target site.

Two flavours:

* ``run_browser_validation`` — generic article-paragraph + bot-wall heuristic
  used for paywall news sites. Counts ``article p``-style selectors and scans
  the markup for explicit captcha/access-denied markers. Auto-shapes the probe
  URL to a stable section index for known publishers (e.g. economist.com root
  → ``/international``) so the validator does not false-negative on homepages.
* ``_run_x_cookie_validation`` — X (ex-Twitter) is upsell-heavy and not
  article-shaped, so we look for ``auth_token`` + ``ct0`` cookies instead,
  which is exactly what the X collector consumes downstream.

``run_browser_validation`` dispatches to ``_run_x_cookie_validation`` whenever
the target is an X-family host.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, urlunparse

from app.models.browser_session import BrowserSessionStatus
from app.platform.browser.bootstrap import (
    _BROWSER_USER_AGENT,
    _require_playwright,
)
from app.platform.browser.hosts import is_wsj_host, is_x_host, missing_x_auth_cookies
from app.platform.observability.logger import get_logger
from app.platform.browser.playwright_runtime import (
    async_playwright,
    default_channel as _browser_default_channel,
    is_patchright_active,
    recommended_launch_args,
)
from app.platform.browser.playwright_stealth import stealth_init_script
from app.utils.url import host_matches, normalize_host

logger = get_logger(__name__)

_WSJ_AUTH_COOKIE_NAMES = frozenset({"djsession", "sso", "session", "usr_prof_v2"})


async def _open_validation_context(
    p: Any,
    *,
    user_data_dir: str | None,
    storage_state_path: str | None,
    session_mode: str,
) -> Any:
    """Open a validation context using the BrowserSession's declared mode."""
    mode = (session_mode or "persistent_profile").strip().lower()
    channel = _browser_default_channel()
    if mode == "storage_state":
        launch_kwargs: Dict[str, Any] = {
            "headless": True,
            "args": recommended_launch_args([]),
        }
        if channel:
            launch_kwargs["channel"] = channel
        browser = await p.chromium.launch(**launch_kwargs)
        context_kwargs: Dict[str, Any] = {}
        if storage_state_path:
            context_kwargs["storage_state"] = storage_state_path
        context = await browser.new_context(**context_kwargs)
        original_close = context.close

        async def _close_with_browser() -> None:
            try:
                await original_close()
            finally:
                await browser.close()

        context.close = _close_with_browser
        return context

    if not user_data_dir:
        raise ValueError("persistent_profile validation requires user_data_dir")
    launch_kwargs = {
        "user_data_dir": user_data_dir,
        "headless": True,
        "args": recommended_launch_args([]),
    }
    if channel:
        launch_kwargs["channel"] = channel
    if is_patchright_active():
        launch_kwargs["no_viewport"] = True
    else:
        launch_kwargs["user_agent"] = _BROWSER_USER_AGENT
        launch_kwargs["args"] = recommended_launch_args([
            "--disable-features=IsolateOrigins,site-per-process",
        ])
    return await p.chromium.launch_persistent_context(**launch_kwargs)


def browser_validation_probe_url(site_url: str, test_url: Optional[str]) -> str:
    """Pick the URL Playwright should open when validating a browser session.

    Many users register ``https://www.<publisher>.com`` (site root). Paywall
    validators that count ``article p`` and scan for marketing copy then
    false-negative: homepages carry nav/footer strings like "subscribe" and
    may not expose enough ``<article><p>`` nodes. Prefer a stable section
    index for known publishers when no explicit ``test_url`` is provided.
    """

    explicit = (test_url or "").strip()
    if explicit:
        return explicit
    base = (site_url or "").strip()
    if not base:
        return ""
    if "://" not in base:
        base = f"https://{base}"
    try:
        parsed = urlparse(base)
        host = normalize_host(base)
        path = (parsed.path or "").rstrip("/")
        if host.endswith("economist.com") and path in ("", "/"):
            scheme = parsed.scheme or "https"
            netloc = parsed.netloc or "www.economist.com"
            return urlunparse((scheme, netloc, "/international", "", "", ""))
    except Exception:  # noqa: BLE001 — never block validation on URL shaping
        logger.debug(
            "browser_validation_probe_url: failed to reshape %r",
            site_url,
            exc_info=True,
        )
    return base


def _validation_html_for_wall_scan(raw_html: str) -> str:
    """Strip executable/style blocks so paywall heuristics don't match JS bundles."""

    html = re.sub(r"(?is)<script\b[^>]*>.*?</script>", "", raw_html)
    html = re.sub(r"(?is)<style\b[^>]*>.*?</style>", "", html)
    html = re.sub(r"(?is)<noscript\b[^>]*>.*?</noscript>", "", html)
    return html.lower()


async def _validation_paragraph_count(page: Any) -> int:
    """Count likely article-body paragraphs; take the max across known patterns."""

    selectors = (
        "article p",
        "[itemprop='articleBody'] p",
        "[itemprop=articleBody] p",
        ".article__body-text p",
        "[data-testid='article-body'] p",
        "[class*='article__body'] p",
        "main [class*='article-body'] p",
        "[class*='article__body-text'] p",
        "[data-test-id='article'] p",
    )
    best = 0
    for sel in selectors:
        try:
            n = await page.locator(sel).count()
            if n > best:
                best = n
        except Exception:  # noqa: BLE001
            continue
    return best


async def run_browser_validation(
    *,
    user_data_dir: str | None,
    site_url: str,
    test_url: Optional[str],
    wait_ms: int,
    min_article_paragraphs: int,
    storage_state_path: str | None = None,
    session_mode: str = "persistent_profile",
) -> Dict[str, Any]:
    _require_playwright("Browser validation")

    # X (ex-Twitter) is not article-based and its home page always shows
    # "Subscribe to Premium" upsells, so the article-paragraph + keyword heuristic
    # used for paywall news sites trips on every successful login. For X we
    # drive the validation off the real signal instead: the presence of
    # ``auth_token`` + ``ct0`` cookies, which is exactly what the X collector
    # reads out of ``runtime_auth.credentials`` afterwards.
    site_host = normalize_host(site_url or "")
    mode = (session_mode or "persistent_profile").strip().lower()
    if is_x_host(site_host):
        return await _run_x_cookie_validation(
            user_data_dir=user_data_dir,
            site_url=site_url,
            storage_state_path=storage_state_path,
            session_mode=mode,
        )
    if is_wsj_host(site_host):
        return await _run_wsj_session_validation(
            user_data_dir=user_data_dir,
            site_url=site_url,
            storage_state_path=storage_state_path,
            session_mode=mode,
        )

    target_url = browser_validation_probe_url(site_url, test_url)
    async with async_playwright() as p:
        context = await _open_validation_context(
            p,
            user_data_dir=user_data_dir,
            storage_state_path=storage_state_path,
            session_mode=mode,
        )
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            if not is_patchright_active():
                await page.add_init_script(stealth_init_script())

            # Warm-up: visit the homepage first so subsequent article hits
            # have a realistic Referer + background cookie refresh. Paywalls
            # (NYT, WSJ) look much harder at cold direct hits to article URLs.
            homepage = site_url if site_url and site_url != target_url else None
            if homepage:
                try:
                    await page.goto(homepage, wait_until="domcontentloaded", timeout=45000)
                    await page.wait_for_timeout(1500)
                except Exception as e:  # noqa: BLE001
                    logger.warning("Validation warm-up to %s failed: %s", homepage, e)

            # ``domcontentloaded`` + an explicit post-load wait tolerates
            # continuously-streaming sites (NYT, WSJ…) that never hit
            # ``networkidle``. We only need enough DOM for paragraph counts.
            try:
                await page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
            except Exception as e:  # noqa: BLE001
                logger.warning("Validation navigation to %s timed out: %s", target_url, e)
            if wait_ms > 0:
                await page.wait_for_timeout(wait_ms)

            raw_html = await page.content()
            paragraph_count = await _validation_paragraph_count(page)
            # Heavy client-rendered hubs (Economist section fronts) may still be
            # mounting article cards after domcontentloaded — give one extra beat.
            if paragraph_count < min_article_paragraphs and site_host.endswith(
                "economist.com"
            ):
                await page.wait_for_timeout(4500)
                paragraph_count = await _validation_paragraph_count(page)
                if paragraph_count < min_article_paragraphs:
                    try:
                        await page.reload(wait_until="domcontentloaded", timeout=45000)
                        if wait_ms > 0:
                            await page.wait_for_timeout(min(wait_ms, 8000))
                        paragraph_count = await _validation_paragraph_count(page)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("Economist validation reload failed: %s", e)

            html = _validation_html_for_wall_scan(raw_html)
            cookies_now = await context.cookies()
            final_url = page.url

            # Scan markup without <script> noise: bundles often contain substrings
            # like "enable javascript" or Cloudflare tokens that are not user-visible.
            # Keep a short list of phrases that usually indicate a real login / bot wall.
            blocked_markers = [
                "captcha",
                "verify you are human",
                "access denied",
            ]
            blocked_hit = next((m for m in blocked_markers if m in html), None)
            if blocked_hit and paragraph_count < min_article_paragraphs:
                severity = BrowserSessionStatus.NEEDS_LOGIN
                message = f"会话可能失效（检测到 {blocked_hit}）"
            elif paragraph_count < min_article_paragraphs:
                severity = BrowserSessionStatus.NEEDS_LOGIN
                message = f"正文段落不足（{paragraph_count}<{min_article_paragraphs}）"
            else:
                severity = BrowserSessionStatus.ACTIVE
                message = f"会话有效（article 段落 {paragraph_count}）"

            return {
                "status": severity,
                "message": message,
                "final_url": final_url,
                "title": await page.title(),
                "cookie_count": len(cookies_now),
                "paragraph_count": paragraph_count,
                "cookies": cookies_now,
            }
        finally:
            await context.close()


def _wsj_auth_cookie_names(cookies: List[dict]) -> set[str]:
    """Return authentication-bearing WSJ/Dow Jones cookie names.

    WSJ's homepage is not article-shaped and its headless response can be a
    DataDome challenge even when the persistent profile is fully signed in.
    Login validity therefore comes from first-party WSJ/Dow Jones SSO cookies,
    not from counting ``article p`` nodes on the homepage.
    """

    names: set[str] = set()
    for cookie in cookies or []:
        domain = str(cookie.get("domain") or "").strip().lower().lstrip(".")
        if not (
            domain == "wsj.com"
            or domain.endswith(".wsj.com")
            or domain == "dowjones.com"
            or domain.endswith(".dowjones.com")
        ):
            continue
        name = str(cookie.get("name") or "").strip().lower()
        if name in _WSJ_AUTH_COOKIE_NAMES:
            names.add(name)
    return names


def _has_wsj_authenticated_session(cookies: List[dict]) -> bool:
    """Require both a WSJ session and a Dow Jones SSO/account signal."""

    names = _wsj_auth_cookie_names(cookies)
    return "djsession" in names and bool(names & {"sso", "session", "usr_prof_v2"})


async def _run_wsj_session_validation(
    *,
    user_data_dir: str | None,
    site_url: str,
    storage_state_path: str | None = None,
    session_mode: str = "persistent_profile",
) -> Dict[str, Any]:
    """WSJ-specific validation based on the session cookies used after login.

    A generic homepage paragraph check produces a deterministic false negative:
    wsj.com has no article body at the root, while a fresh headless visit may
    independently trigger DataDome.  The persistent profile remains useful to
    article fetches when it carries ``DJSESSION`` plus a Dow Jones SSO signal.
    """

    async with async_playwright() as p:
        context = await _open_validation_context(
            p,
            user_data_dir=user_data_dir,
            storage_state_path=storage_state_path,
            session_mode=session_mode,
        )
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            if not is_patchright_active():
                await page.add_init_script(stealth_init_script())
            probe_url = "https://www.wsj.com/"
            try:
                await page.goto(probe_url, wait_until="domcontentloaded", timeout=45000)
                await page.wait_for_timeout(1200)
            except Exception as exc:  # noqa: BLE001 - cookies remain inspectable
                logger.warning("WSJ validation navigation to %s failed: %s", probe_url, exc)

            cookies_now = await context.cookies()
            final_url = page.url or probe_url
            title = await page.title()
            auth_names = _wsj_auth_cookie_names(cookies_now)
            logged_in = _has_wsj_authenticated_session(cookies_now)
            bounced_to_login = any(
                marker in final_url.lower()
                for marker in ("/login", "/signin", "/sign-in", "accounts.dowjones.com")
            )

            if logged_in and not bounced_to_login:
                message = "WSJ 登录态有效（DJSESSION 与 Dow Jones SSO 会话已就绪）"
                status = BrowserSessionStatus.ACTIVE
            elif bounced_to_login:
                message = "WSJ 未登录（被重定向到登录页）"
                status = BrowserSessionStatus.NEEDS_LOGIN
            else:
                missing = []
                if "djsession" not in auth_names:
                    missing.append("DJSESSION")
                if not auth_names.intersection({"sso", "session", "usr_prof_v2"}):
                    missing.append("Dow Jones SSO")
                message = f"WSJ 登录态不完整（缺少 {', '.join(missing) or '会话 Cookie'}）"
                status = BrowserSessionStatus.NEEDS_LOGIN

            return {
                "status": status,
                "message": message,
                "final_url": final_url,
                "title": title,
                "cookie_count": len(cookies_now),
                "paragraph_count": 0,
                "cookies": cookies_now,
                "validation_kind": "wsj_session_cookies",
            }
        finally:
            await context.close()


async def _run_x_cookie_validation(
    *,
    user_data_dir: str | None,
    site_url: str,
    storage_state_path: str | None = None,
    session_mode: str = "persistent_profile",
) -> Dict[str, Any]:
    """X-specific validation: succeed iff ``auth_token`` + ``ct0`` cookies exist.

    Navigates to ``x.com/home`` so Playwright can pick up the persisted
    cookies via the persistent context, then checks for the two auth cookies
    the X collector actually consumes. Staying on ``/home`` (rather than
    bouncing to ``/i/flow/login``) is an extra signal but not strictly
    required — a fresh auth_token is what matters.
    """

    async with async_playwright() as p:
        context = await _open_validation_context(
            p,
            user_data_dir=user_data_dir,
            storage_state_path=storage_state_path,
            session_mode=session_mode,
        )
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            if not is_patchright_active():
                await page.add_init_script(stealth_init_script())
            probe_url = "https://x.com/home"
            try:
                await page.goto(probe_url, wait_until="domcontentloaded", timeout=45000)
                await page.wait_for_timeout(1500)
            except Exception as e:  # noqa: BLE001
                logger.warning("X validation navigation to %s failed: %s", probe_url, e)
            cookies_now = await context.cookies()
            final_url = page.url or probe_url
            title = await page.title()
            missing = missing_x_auth_cookies(cookies_now)
            bounced_to_login = "/i/flow/login" in final_url or "/login" in final_url
            if not missing and not bounced_to_login:
                return {
                    "status": BrowserSessionStatus.ACTIVE,
                    "message": f"会话有效（auth_token + ct0 已就绪，共 {len(cookies_now)} 个 cookie）",
                    "final_url": final_url,
                    "title": title,
                    "cookie_count": len(cookies_now),
                    "paragraph_count": 0,
                    "cookies": cookies_now,
                }
            if bounced_to_login:
                msg = "未登录（被重定向到 X 登录页）"
            else:
                msg = f"缺少关键 cookie：{', '.join(missing) or '未知'}"
            return {
                "status": BrowserSessionStatus.NEEDS_LOGIN,
                "message": msg,
                "final_url": final_url,
                "title": title,
                "cookie_count": len(cookies_now),
                "paragraph_count": 0,
                "cookies": cookies_now,
            }
        finally:
            await context.close()
