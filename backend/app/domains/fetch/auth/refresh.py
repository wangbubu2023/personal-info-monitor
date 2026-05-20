"""Refresh stale auth cookies for a source by replaying the login flow.

Called by the collector stage immediately before fetching. Decision flow:

1. If the source has no ``auth_config`` or it is not password-based, no-op.
2. If existing cookies still ``cookies_appear_valid``, no-op.
3. If ``cookie_mode == "manual"``, never trigger auto-login (return a warning
   that the user must update cookies manually).
4. Otherwise, drive Playwright through the configured login URL via
   ``platform.browser.login_and_capture_cookies``, merge the captured cookies
   back into the credential blob, re-encrypt, and commit.

Failures are returned as a ``(creds, warning_text)`` tuple so the collector
can surface them through the pipeline warning channel without aborting fetch.
"""

from __future__ import annotations

from app.platform.auth.cookies import cookies_appear_valid
from app.platform.browser.login_capture import login_and_capture_cookies
from app.utils.datetime import utcnow_naive
from app.utils.logger import get_logger
from app.utils.url import normalize_host

logger = get_logger(__name__)

_DEFAULT_LOGIN_URLS = {
    "wsj.com": "https://www.wsj.com/login",
}


async def maybe_refresh_auth_cookies(db, source, creds: dict) -> tuple[dict, str | None]:
    if not source.auth_config:
        return creds, None
    auth_type = (
        source.auth_config.auth_type.value
        if hasattr(source.auth_config.auth_type, "value")
        else str(source.auth_config.auth_type).lower()
    )
    if auth_type != "password":
        return creds, None

    cookie_mode = str(creds.get("cookie_mode") or "").strip().lower()
    cookies = creds.get("cookies") if isinstance(creds.get("cookies"), dict) else {}
    if cookies:
        cookies_valid = True
        try:
            cookies_valid = bool(await cookies_appear_valid(source.url, cookies))
        except Exception as exc:  # noqa: BLE001 - precheck must not abort refresh on any error
            logger.warning("Cookie precheck failed for source %s: %s", source.id, exc)
        if cookies_valid:
            return creds, None
        if cookie_mode == "manual":
            return creds, "手动 Cookie 可能已失效，请更新后重试"
        logger.warning(
            "Cookies appear stale for source %s; attempting auto-login refresh",
            source.id,
        )

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
        cookie_dict = await login_and_capture_cookies(
            site_url=source.url,
            login_url=login_url,
            username=str(username),
            password=str(password),
            login_selectors=source.auth_config.login_selectors
            if isinstance(source.auth_config.login_selectors, dict)
            else {},
        )
    except Exception as exc:  # noqa: BLE001 - login surface (Playwright/network) raises many error types
        reason = str(exc)
        logger.warning("Auto-login failed for source %s: %s", source.id, reason)
        return creds, f"自动登录失败: {reason}"

    if not cookie_dict:
        logger.warning("Auto-login returned empty cookies for source %s", source.id)
        return creds, "自动登录失败: 未获取到 cookies"

    merged = dict(creds)
    merged["cookies"] = cookie_dict
    merged["cookie_mode"] = "auto"
    merged["cookie_updated_at"] = utcnow_naive().isoformat() + "Z"
    try:
        from app.platform.security.encryption import encrypt_data

        source.auth_config.credentials = encrypt_data(merged)
        source.auth_config.last_validated_at = utcnow_naive()
        db.commit()
        logger.info("Auto-login refreshed cookies for source %s", source.id)
        return merged, None
    except Exception as exc:  # noqa: BLE001 - persistence may fail with various ORM/encryption errors
        logger.warning(
            "Failed to persist refreshed cookies for source %s: %s",
            source.id,
            exc,
        )
        return creds, f"自动登录失败: 持久化 cookies 失败: {exc}"
