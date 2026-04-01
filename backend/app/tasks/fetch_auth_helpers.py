"""Authentication helpers for fetch task orchestration."""

import json
from typing import List
from uuid import UUID

from app.utils.cookies import normalize_cookie_dict
from app.utils.datetime import utcnow_naive
from app.utils.logger import get_logger
from app.utils.url import normalize_host

logger = get_logger(__name__)

_DEFAULT_LOGIN_URLS = {
    "wsj.com": "https://www.wsj.com/login",
}

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


def build_browser_session_runtime(db, source) -> dict | None:
    metadata = source.metadata_ if isinstance(source.metadata_, dict) else {}
    raw_id = metadata.get("browser_session_id")
    if not raw_id:
        return None

    try:
        session_id = UUID(str(raw_id))
    except Exception as e:
        logger.debug(f"Invalid browser_session_id for source {getattr(source, 'id', 'unknown')}: {e}")
        return None

    try:
        from app.models.browser_session import BrowserSession

        session = db.query(BrowserSession).filter(BrowserSession.id == session_id).first()
    except Exception as e:
        logger.debug(f"Failed to load browser session {session_id}: {e}")
        return None
    if not session:
        return None

    return {
        "id": str(session.id),
        "site_url": session.site_url,
        "site_host": session.site_host,
        "profile_name": session.profile_name,
        "user_data_dir": session.user_data_dir,
        "storage_state_path": session.storage_state_path,
        "status": session.status.value if hasattr(session.status, "value") else str(session.status),
    }


def try_parse_auth_credentials(auth_config) -> dict:
    if not auth_config or not getattr(auth_config, "credentials", None):
        return {}
    site_host = normalize_host(getattr(auth_config, "site_url", ""))
    try:
        from app.utils.encryption import decrypt_data

        raw = decrypt_data(auth_config.credentials)
        if isinstance(raw, str):
            creds = json.loads(raw)
            if isinstance(creds, dict):
                if "cookies" in creds:
                    creds["cookies"] = normalize_cookie_dict(
                        creds.get("cookies"),
                        site_host=site_host,
                    )
                return creds
            return {}
        if isinstance(raw, dict):
            if "cookies" in raw:
                raw["cookies"] = normalize_cookie_dict(
                    raw.get("cookies"),
                    site_host=site_host,
                )
            return raw
        return {}
    except Exception as e:
        logger.debug(f"Failed to parse auth credentials for config {getattr(auth_config, 'id', 'unknown')}: {e}")
        return {}


def _domain_match(cookie_domain: str, target_host: str) -> bool:
    domain = (cookie_domain or "").lstrip(".").lower()
    host = (target_host or "").lower()
    if not domain or not host:
        return False
    return host == domain or host.endswith("." + domain) or domain.endswith("." + host)


async def _find_first_selector(page, candidates):
    for selector in candidates:
        if not selector:
            continue
        try:
            if await page.locator(selector).count() > 0:
                return selector
        except Exception as e:
            logger.debug(f"Selector probe failed for '{selector}': {e}")
            continue
    return None


async def _page_has_captcha(page) -> bool:
    try:
        html = (await page.content()).lower()
    except Exception as e:
        logger.debug(f"Failed to inspect page content for captcha markers: {e}")
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
    except Exception as e:
        logger.debug(f"Failed to inspect frame URLs for captcha markers: {e}")
        frame_urls = []
    return any(("captcha" in u) or ("challenge" in u) for u in frame_urls)


async def _login_and_capture_cookies(
    site_url: str,
    login_url: str,
    username: str,
    password: str,
    login_selectors: dict | None = None,
) -> dict:
    from playwright.async_api import async_playwright

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
                    except Exception as e:
                        logger.debug(f"Success selector wait failed, fallback to networkidle: {e}")
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
                    if _domain_match(domain, site_host):
                        cookie_dict[str(name)] = str(value)
                return cookie_dict
            finally:
                try:
                    await context.close()
                except Exception as e:
                    logger.debug(f"Failed to close login context for {site_url}: {e}")
        finally:
            try:
                await browser.close()
            except Exception as e:
                logger.debug(f"Failed to close login browser for {site_url}: {e}")


async def cookies_appear_valid(site_url: str, cookies: dict) -> bool:
    """Best-effort precheck for cookie validity to avoid stale auth sessions."""
    import aiohttp
    from yarl import URL

    if not site_url or not isinstance(cookies, dict) or not cookies:
        return False

    markers = (
        "sign in",
        "log in",
        "subscribe",
        "create account",
        "verify you are human",
        "captcha",
        "access denied",
    )
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        cookie_jar = aiohttp.CookieJar()
        url_obj = URL(site_url)
        for name, value in cookies.items():
            key = str(name or "").strip()
            if not key or value is None:
                continue
            cookie_jar.update_cookies({key: str(value)}, response_url=url_obj)

        async with aiohttp.ClientSession(timeout=timeout, cookie_jar=cookie_jar) as session:
            async with session.get(
                site_url,
                allow_redirects=True,
            ) as response:
                if response.status in {401, 403}:
                    return False
                final_url = str(response.url).lower()
                if any(token in final_url for token in ("/login", "/signin", "/sign-in", "/subscribe", "captcha")):
                    return False
                body = (await response.text(errors="ignore"))[:5000].lower()
                if any(marker in body for marker in markers):
                    return False
                return True
    except Exception as e:
        logger.debug(f"Skip cookie precheck for {site_url}: {e}")
        return True


async def maybe_refresh_auth_cookies(db, source, creds: dict) -> tuple[dict, str | None]:
    if not source.auth_config:
        return creds, None
    auth_type = source.auth_config.auth_type.value if hasattr(source.auth_config.auth_type, "value") else str(source.auth_config.auth_type).lower()
    if auth_type != "password":
        return creds, None

    cookie_mode = str(creds.get("cookie_mode") or "").strip().lower()
    cookies = creds.get("cookies") if isinstance(creds.get("cookies"), dict) else {}
    if cookies:
        cookies_valid = True
        try:
            cookies_valid = bool(await cookies_appear_valid(source.url, cookies))
        except Exception as e:
            logger.warning(f"Cookie precheck failed for source {source.id}: {e}")
        if cookies_valid:
            return creds, None
        if cookie_mode == "manual":
            return creds, "手动 Cookie 可能已失效，请更新后重试"
        logger.warning(f"Cookies appear stale for source {source.id}; attempting auto-login refresh")

    if cookie_mode == "manual":
        return creds, "手动 Cookie 优先模式：未检测到可用 Cookie，已跳过自动登录"

    username = creds.get("username")
    password = creds.get("password")
    if not username or not password:
        return creds, None

    login_url = source.auth_config.login_url
    if not login_url:
        source_host = normalize_host(source.url)
        login_url = _DEFAULT_LOGIN_URLS.get(source_host)
        if not login_url:
            login_url = source.url if "://" in (source.url or "") else f"https://{source.url}"

    try:
        cookie_dict = await _login_and_capture_cookies(
            site_url=source.url,
            login_url=login_url,
            username=str(username),
            password=str(password),
            login_selectors=source.auth_config.login_selectors if isinstance(source.auth_config.login_selectors, dict) else {},
        )
    except Exception as e:
        reason = str(e)
        logger.warning(f"Auto-login failed for source {source.id}: {reason}")
        return creds, f"自动登录失败: {reason}"

    if not cookie_dict:
        logger.warning(f"Auto-login returned empty cookies for source {source.id}")
        return creds, "自动登录失败: 未获取到 cookies"

    merged = dict(creds)
    merged["cookies"] = cookie_dict
    merged["cookie_mode"] = "auto"
    merged["cookie_updated_at"] = utcnow_naive().isoformat() + "Z"
    try:
        from app.utils.encryption import encrypt_data

        source.auth_config.credentials = encrypt_data(merged)
        source.auth_config.last_validated_at = utcnow_naive()
        db.commit()
        logger.info(f"Auto-login refreshed cookies for source {source.id}")
        return merged, None
    except Exception as e:
        logger.warning(f"Failed to persist refreshed cookies for source {source.id}: {e}")
        return creds, f"自动登录失败: 持久化 cookies 失败: {e}"


def auth_warning_entry(auth_warning: str | None) -> tuple[str, str, str] | None:
    text = str(auth_warning or "").strip()
    if not text:
        return None
    lowered = text.lower()
    if "captcha" in lowered or "challenge detected" in lowered or "人机" in lowered:
        return ("auth_captcha", "error", "登录受阻：检测到验证码/人机挑战")
    if text.startswith("自动登录失败"):
        return ("auth_login_failed", "error", text)
    if "手动 Cookie 优先模式" in text:
        return ("cookie_missing_manual_mode", "error", text)
    return ("auth_warning", "warning", text)


def cookie_hydration_warning_entry(source, runtime_auth: dict | None) -> tuple[str, str, str] | None:
    source_type = source.type.value if hasattr(source.type, "value") else str(source.type).lower()
    if source_type != "website":
        return None
    if not isinstance(runtime_auth, dict):
        return None
    creds = runtime_auth.get("credentials", {}) if isinstance(runtime_auth.get("credentials"), dict) else {}
    cookies = normalize_cookie_dict(creds.get("cookies"))
    browser_session = runtime_auth.get("browser_session") if isinstance(runtime_auth.get("browser_session"), dict) else {}
    has_browser_session = bool(str(browser_session.get("user_data_dir") or "").strip())
    if not cookies and not has_browser_session:
        return None

    diag = getattr(source, "_runtime_fetch_diag", None)
    if not isinstance(diag, dict):
        return None
    attempted = int(diag.get("attempted") or 0)
    hydrated = int(diag.get("hydrated") or 0)
    failures = diag.get("failures") if isinstance(diag.get("failures"), dict) else {}
    if attempted <= 0:
        return None
    if hydrated >= attempted:
        return None

    shell_fail = int(failures.get("shell_page", 0))
    wrapper_fail = int(failures.get("wrapper_unresolved", 0))
    if hydrated == 0:
        if shell_fail > 0:
            return (
                "fulltext_shell_page",
                "error",
                f"全文抓取失败：返回壳页面（可能 Cookie 失效或访问受限，尝试 {attempted} 篇）",
            )
        if wrapper_fail > 0:
            return (
                "fulltext_wrapper_unresolved",
                "warning",
                f"全文抓取受限：Google 包装链接未能解析为原文（尝试 {attempted} 篇）",
            )
        return (
            "fulltext_missing",
            "warning",
            f"全文抓取未命中：已尝试 {attempted} 篇，成功 0 篇",
        )

    return (
        "fulltext_partial",
        "warning",
        f"全文抓取部分成功：尝试 {attempted} 篇，成功 {hydrated} 篇",
    )
