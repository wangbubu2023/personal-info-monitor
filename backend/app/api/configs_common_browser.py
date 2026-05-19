"""Browser-session + Playwright orchestration helpers.

Split from ``configs_common.py`` (audit 2026-04-20 §8.2). Anything that
touches Chromium / filesystem profiles lives here; credential + cookie logic
stays in the sibling ``configs_common_auth`` / ``configs_common_cookies``
modules.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, urlunparse

from app.utils.logger import get_logger

logger = get_logger(__name__)

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features import PlaywrightDisabledError, playwright_enabled
from app.models import Source
from app.models.auth_config import AuthConfig
from app.models.browser_session import BrowserSession, BrowserSessionStatus
from app.utils.cookies import cookie_domains_for_host
from app.utils.datetime import to_iso_z, utcnow_naive
from app.utils.encryption import encrypt_data
from app.utils.playwright_runtime import (
    async_playwright,
    default_channel as _browser_default_channel,
    is_patchright_active,
    recommended_launch_args,
)
from app.utils.playwright_stealth import stealth_init_script
from app.utils.url import host_matches, normalize_host


def profiles_root() -> Path:
    root = os.getenv("PLAYWRIGHT_PROFILE_ROOT", str(Path.home() / ".pim" / "playwright-sessions"))
    path = Path(root).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def slugify_profile_name(text: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "-" for ch in (text or "").strip().lower())
    collapsed = "-".join([p for p in cleaned.split("-") if p])
    return collapsed or f"session-{uuid.uuid4().hex[:8]}"


def serialize_browser_session(session: BrowserSession) -> dict:
    return {
        "id": str(session.id),
        "site_url": session.site_url,
        "site_host": session.site_host,
        "profile_name": session.profile_name,
        "user_data_dir": session.user_data_dir,
        "storage_state_path": session.storage_state_path,
        "auth_config_id": str(session.auth_config_id) if session.auth_config_id else None,
        "status": session.status.value if hasattr(session.status, "value") else str(session.status),
        "last_validated_at": to_iso_z(session.last_validated_at),
        "last_error": session.last_error,
        "metadata_": session.metadata_ if isinstance(session.metadata_, dict) else {},
        "created_at": to_iso_z(session.created_at),
        "updated_at": to_iso_z(session.updated_at),
    }


_X_HOSTS: frozenset[str] = frozenset({"x.com", "twitter.com"})


def is_x_host(host: Optional[str]) -> bool:
    """Whether ``host`` refers to the X (ex-Twitter) family of sites."""
    return normalize_host(host or "") in _X_HOSTS


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
        logger.debug("browser_validation_probe_url: failed to reshape %r", site_url, exc_info=True)
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


async def ensure_x_shared_auth_config(
    db: AsyncSession,
    site_url: str,
    site_host: str,
) -> Optional[AuthConfig]:
    """Return (or create) a shared X cookie auth_config for x.com/twitter.com.

    Browser-session-driven X login writes cookies into this row; the X
    collector then reads ``auth_token`` / ``ct0`` out of it through the
    existing ``runtime_auth.credentials`` path. If a shared X profile already
    exists we reuse it rather than multiplying rows.
    """
    from app.models.auth_config import AuthStatus, AuthType

    if not is_x_host(site_host):
        return None

    result = await db.execute(select(AuthConfig))
    for cfg in result.scalars().all():
        cfg_host = normalize_host(cfg.site_url)
        if cfg_host not in _X_HOSTS:
            continue
        cfg_type = cfg.auth_type.value if hasattr(cfg.auth_type, "value") else str(cfg.auth_type or "").lower()
        if bool(cfg.is_shared) and cfg_type == "cookie":
            return cfg

    config = AuthConfig(
        name="X 浏览器会话",
        site_url=site_url or "https://x.com",
        auth_type=AuthType.COOKIE,
        is_shared=True,
        status=AuthStatus.ACTIVE,
        login_selectors={},
    )
    db.add(config)
    await db.flush()
    logger.info("Auto-created shared X auth_config %s for browser session", config.id)
    return config


def sync_cookies_to_auth_config(
    auth_config: Optional[AuthConfig],
    cookies: Optional[List[Dict[str, Any]]],
    site_host: str,
    *,
    min_cookies: int = 1,
) -> bool:
    """Write host-matching cookies from a browser context into ``auth_config``.

    Returns True if the config's ``credentials`` payload was actually
    modified. ``min_cookies=1`` lets the X flow land even a partial cookie
    set (just ``auth_token`` + ``ct0`` is enough for the X collector); the
    paywall sites typically need far more and use the validate path's
    stricter threshold.
    """
    if not auth_config or not cookies:
        return False

    from app.api.configs_common_auth import decrypt_auth_credentials

    cookie_dict: Dict[str, str] = {}
    for item in cookies:
        name = str(item.get("name") or "").strip()
        value = item.get("value")
        domain = str(item.get("domain") or "").lstrip(".").lower()
        if not name or value is None:
            continue
        if host_matches(site_host, domain):
            cookie_dict[name] = str(value)

    if not cookie_dict or len(cookie_dict) < min_cookies:
        return False

    existing = decrypt_auth_credentials(auth_config)
    existing["cookies"] = cookie_dict
    existing["cookie_mode"] = "manual"
    existing["cookie_updated_at"] = utcnow_naive().isoformat() + "Z"
    auth_config.credentials = encrypt_data(existing)
    auth_config.last_validated_at = utcnow_naive()
    return True


async def bind_browser_session_to_sources(db: AsyncSession, session: BrowserSession) -> int:
    """Link a browser session to every matching source.

    - Website sources: stamp ``metadata_.browser_session_id`` so the collector
      can pick it up from ``runtime_auth.browser_session``.
    - X sources: the X collector still consumes cookies out of
      ``auth_config.credentials`` (bootstrap + validate sync to that config),
      so the binding is expressed by pointing ``source.auth_config_id`` at the
      session's linked auth config. That way the existing
      ``collector_stage`` code path works unchanged.

    We purposely match by host (``x.com`` / ``twitter.com`` are treated as the
    same family) so a session created for x.com also covers legacy twitter.com
    source URLs.
    """
    target_host = normalize_host(session.site_url) or session.site_host
    if not target_host:
        return 0
    result = await db.execute(select(Source))
    sources = result.scalars().all()
    bound = 0
    session_is_x = is_x_host(target_host)
    for source in sources:
        source_type = source.type.value if hasattr(source.type, "value") else str(source.type).lower()
        source_host = normalize_host(source.url)
        type_lower = (source_type or "").lower()

        if type_lower == "website":
            if not host_matches(source_host, target_host):
                continue
            metadata = dict(source.metadata_ or {})
            if str(metadata.get("browser_session_id") or "") == str(session.id):
                continue
            metadata["browser_session_id"] = str(session.id)
            source.metadata_ = metadata
            source.auth_required = True
            bound += 1
        elif type_lower == "x" and session_is_x and session.auth_config_id:
            # X抓取依赖 auth_config.credentials.cookies；把 X 源统一指向浏览器
            # 会话关联的那份 auth_config，cookie 同步完成后即可直接使用。
            if source.auth_config_id == session.auth_config_id:
                continue
            source.auth_config_id = session.auth_config_id
            source.auth_required = True
            bound += 1
    return bound


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
                cookie_holder: Dict[str, Any] = {"cookies": []}

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


async def run_browser_validation(
    *,
    user_data_dir: str,
    site_url: str,
    test_url: Optional[str],
    wait_ms: int,
    min_article_paragraphs: int,
) -> Dict[str, Any]:
    _require_playwright("Browser validation")

    # X (ex-Twitter) is not article-based and its home page always shows
    # "Subscribe to Premium" upsells, so the article-paragraph + keyword heuristic
    # used for paywall news sites trips on every successful login. For X we
    # drive the validation off the real signal instead: the presence of
    # ``auth_token`` + ``ct0`` cookies, which is exactly what the X collector
    # reads out of ``runtime_auth.credentials`` afterwards.
    site_host = normalize_host(site_url or "")
    if is_x_host(site_host):
        return await _run_x_cookie_validation(
            user_data_dir=user_data_dir,
            site_url=site_url,
        )

    target_url = browser_validation_probe_url(site_url, test_url)
    async with async_playwright() as p:
        launch_kwargs: Dict[str, Any] = {
            "user_data_dir": user_data_dir,
            "headless": True,
            "args": recommended_launch_args([]),
        }
        channel = _browser_default_channel()
        if channel:
            launch_kwargs["channel"] = channel
        if is_patchright_active():
            launch_kwargs["no_viewport"] = True
        else:
            launch_kwargs["user_agent"] = _BROWSER_USER_AGENT
            # Vanilla playwright benefits from disabling site isolation to avoid
            # cross-origin iframe separation on news paywalls; patchright
            # actively discourages extra launch flags.
            launch_kwargs["args"] = recommended_launch_args([
                "--disable-features=IsolateOrigins,site-per-process",
            ])
        context = await p.chromium.launch_persistent_context(**launch_kwargs)
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


async def _run_x_cookie_validation(
    *,
    user_data_dir: str,
    site_url: str,
) -> Dict[str, Any]:
    """X-specific validation: succeed iff ``auth_token`` + ``ct0`` cookies exist.

    Navigates to ``x.com/home`` so Playwright can pick up the persisted
    cookies via the persistent context, then checks for the two auth cookies
    the X collector actually consumes. Staying on ``/home`` (rather than
    bouncing to ``/i/flow/login``) is an extra signal but not strictly
    required — a fresh auth_token is what matters.
    """
    async with async_playwright() as p:
        launch_kwargs: Dict[str, Any] = {
            "user_data_dir": user_data_dir,
            "headless": True,
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
            cookie_names = {
                str(c.get("name") or "").lower()
                for c in cookies_now
                if host_matches(normalize_host(c.get("domain", "")), "x.com")
                or host_matches(normalize_host(c.get("domain", "")), "twitter.com")
            }
            has_auth_token = "auth_token" in cookie_names
            has_ct0 = "ct0" in cookie_names
            bounced_to_login = "/i/flow/login" in final_url or "/login" in final_url
            if has_auth_token and has_ct0 and not bounced_to_login:
                return {
                    "status": BrowserSessionStatus.ACTIVE,
                    "message": f"会话有效（auth_token + ct0 已就绪，共 {len(cookies_now)} 个 cookie）",
                    "final_url": final_url,
                    "title": title,
                    "cookie_count": len(cookies_now),
                    "paragraph_count": 0,
                    "cookies": cookies_now,
                }
            missing: List[str] = []
            if not has_auth_token:
                missing.append("auth_token")
            if not has_ct0:
                missing.append("ct0")
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
