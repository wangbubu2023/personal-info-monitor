"""Shared helpers for configuration API modules."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Source
from app.models.auth_config import APIConfig, AuthConfig, AuthStatus
from app.models.browser_session import BrowserSession, BrowserSessionStatus
from app.utils.cookies import cookie_domains_for_host, normalize_cookie_dict
from app.utils.encryption import decrypt_data
from app.utils.playwright_stealth import stealth_init_script
from app.utils.url import host_matches, normalize_host
from app.utils.datetime import to_iso_z


def mask_api_key(key: str) -> str:
    if not key or len(key) < 8:
        return "****"
    return f"{key[:4]}...{key[-4:]}"


def decrypt_api_credentials(config: APIConfig) -> dict:
    """Best-effort decrypt API credentials JSON."""
    try:
        if not config.encrypted_credentials:
            return {}
        raw = decrypt_data(config.encrypted_credentials)
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        return {}
    except Exception:
        return {}


def serialize_api_config(config: APIConfig) -> dict:
    creds = decrypt_api_credentials(config)
    masked_key = mask_api_key(creds["api_key"]) if creds.get("api_key") else None
    additional = creds.get("additional") or {}

    return {
        "id": str(config.id),
        "platform": config.platform,
        "name": config.name,
        "status": config.status.value if hasattr(config.status, "value") else config.status,
        "last_used_at": to_iso_z(config.last_used_at),
        "rate_limit_info": config.rate_limit_info if isinstance(config.rate_limit_info, dict) else {},
        "created_at": to_iso_z(config.created_at),
        "updated_at": to_iso_z(config.updated_at),
        "masked_key": masked_key,
        "api_base": additional.get("api_base"),
    }


def decrypt_auth_credentials(config: AuthConfig) -> dict:
    if not config.credentials:
        return {}
    try:
        raw = decrypt_data(config.credentials)
        if isinstance(raw, str):
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def has_any_credentials(credentials: dict) -> bool:
    if not isinstance(credentials, dict):
        return False
    cookies = credentials.get("cookies")
    if isinstance(cookies, dict) and any(str(k).strip() and str(v).strip() for k, v in cookies.items()):
        return True
    username = str(credentials.get("username") or "").strip()
    password = str(credentials.get("password") or "").strip()
    api_key = str(credentials.get("api_key") or "").strip()
    return bool(username or password or api_key)


def serialize_auth_config(config: AuthConfig) -> dict:
    credentials = decrypt_auth_credentials(config)
    has_credentials = has_any_credentials(credentials)
    bound_source_count = len(getattr(config, "sources", []) or [])

    return {
        "id": str(config.id),
        "name": config.name,
        "site_url": config.site_url,
        "auth_type": config.auth_type.value if hasattr(config.auth_type, "value") else config.auth_type,
        "is_shared": bool(config.is_shared),
        "login_url": config.login_url,
        "status": config.status.value if hasattr(config.status, "value") else config.status,
        "last_validated_at": to_iso_z(config.last_validated_at),
        "login_selectors": config.login_selectors if isinstance(config.login_selectors, dict) else {},
        "created_at": to_iso_z(config.created_at),
        "updated_at": to_iso_z(config.updated_at),
        "has_credentials": has_credentials,
        "bound_source_count": bound_source_count,
    }


def normalize_cookies_input(cookies, *, site_host: str | None = None) -> dict:
    if cookies is None:
        return {}

    parsed = normalize_cookie_dict(cookies, site_host=site_host)
    if parsed:
        return parsed

    if isinstance(cookies, str) and not cookies.strip():
        return {}
    if isinstance(cookies, dict) and len(cookies) == 0:
        return {}

    raise ValueError("Cookie 解析失败，请使用 `name1=value1; name2=value2` 格式。")


async def bind_auth_config_to_sources(db: AsyncSession, config: AuthConfig) -> int:
    """Bind auth config to matching website sources, ensuring persistence on source rows."""
    auth_host = normalize_host(config.site_url)
    if not auth_host:
        return 0

    result = await db.execute(select(Source))
    sources = result.scalars().all()
    bound = 0

    for source in sources:
        source_type = source.type.value if hasattr(source.type, "value") else str(source.type).lower()
        if source_type != "website":
            continue

        source_host = normalize_host(source.url)
        if not host_matches(source_host, auth_host):
            continue

        if not source.auth_required and source.auth_config_id != config.id:
            continue

        if source.auth_config_id and source.auth_config_id != config.id:
            continue

        changed = False
        if source.auth_config_id != config.id:
            source.auth_config_id = config.id
            changed = True
        if not source.auth_required:
            source.auth_required = True
            changed = True
        if changed:
            bound += 1

    return bound


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


def extract_auth_cookies_for_host(config: Optional[AuthConfig], site_host: str) -> Dict[str, str]:
    if not config:
        return {}
    credentials = decrypt_auth_credentials(config)
    cookies = credentials.get("cookies") if isinstance(credentials.get("cookies"), dict) else {}
    normalized = normalize_cookie_dict(cookies, site_host=site_host)
    return normalized if normalized else {}


async def bind_browser_session_to_sources(db: AsyncSession, session: BrowserSession) -> int:
    target_host = normalize_host(session.site_url) or session.site_host
    if not target_host:
        return 0
    result = await db.execute(select(Source))
    sources = result.scalars().all()
    bound = 0
    for source in sources:
        source_type = source.type.value if hasattr(source.type, "value") else str(source.type).lower()
        if source_type != "website":
            continue
        source_host = normalize_host(source.url)
        if not host_matches(source_host, target_host):
            continue
        metadata = dict(source.metadata_ or {})
        if str(metadata.get("browser_session_id") or "") == str(session.id):
            continue
        metadata["browser_session_id"] = str(session.id)
        source.metadata_ = metadata
        source.auth_required = True
        bound += 1
    return bound


async def run_browser_bootstrap(
    *,
    user_data_dir: str,
    site_url: str,
    site_host: str,
    cookies: Dict[str, str],
    headless: bool,
    dwell_seconds: int,
) -> Dict[str, Any]:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )
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
            await page.add_init_script(stealth_init_script())
            await page.goto(site_url, wait_until="networkidle", timeout=90000)
            if dwell_seconds > 0:
                await page.wait_for_timeout(dwell_seconds * 1000)
            cookies_now = await context.cookies()
            return {
                "final_url": page.url,
                "title": await page.title(),
                "cookie_count": len(cookies_now),
            }
        finally:
            await context.close()


async def run_browser_validation(
    *,
    user_data_dir: str,
    site_url: str,
    test_url: Optional[str],
    wait_ms: int,
    min_article_paragraphs: int,
) -> Dict[str, Any]:
    from playwright.async_api import async_playwright

    target_url = (test_url or site_url or "").strip() or site_url
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            await page.add_init_script(stealth_init_script())
            await page.goto(target_url, wait_until="networkidle", timeout=90000)
            if wait_ms > 0:
                await page.wait_for_timeout(wait_ms)

            html = (await page.content()).lower()
            paragraph_count = await page.locator("article p").count()
            cookies_now = await context.cookies()
            final_url = page.url

            blocked_markers = [
                "captcha",
                "verify you are human",
                "subscribe",
                "sign in",
                "log in",
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
