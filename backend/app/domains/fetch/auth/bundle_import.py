"""Import Auth Bundles into PIM's existing auth storage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth_config import AuthConfig, AuthStatus, AuthType
from app.models.browser_session import BrowserSession, BrowserSessionMode, BrowserSessionStatus
from app.models.source import Source, SourceType
from app.platform.auth.bundle import (
    AuthBundleError,
    bundle_cookie_dict,
    filtered_storage_state,
    validate_auth_bundle,
)
from app.platform.auth.credentials import decrypt_auth_credentials
from app.platform.browser.hosts import is_x_host
from app.platform.browser.profiles import profiles_root, slugify_profile_name
from app.platform.security.encryption import encrypt_data
from app.utils.cookies import normalize_cookie_dict
from app.utils.datetime import utcnow_naive
from app.utils.url import host_matches, normalize_host


async def import_auth_bundle(
    db: AsyncSession,
    bundle: dict[str, Any],
    *,
    name: str | None = None,
    bind_matching_sources: bool = True,
    create_browser_session: bool = True,
) -> dict[str, Any]:
    normalized = validate_auth_bundle(bundle)
    site_url = normalized["site_url"]
    site_host = normalized["site_host"]
    cookies = normalize_cookie_dict(normalized["cookies"], site_host=site_host)
    if not cookies:
        cookies = bundle_cookie_dict(normalized)
    if not cookies:
        raise AuthBundleError("Auth Bundle contains no usable non-expired cookies")

    storage_state_path = None
    storage_state = filtered_storage_state(normalized.get("storage_state"), site_host)
    if storage_state and storage_state.get("cookies"):
        storage_state_path = _write_storage_state(site_host, storage_state)

    auth_config = await _find_matching_auth_config(db, site_host)
    if auth_config is None:
        auth_config = AuthConfig(
            name=name or normalized.get("name") or f"{site_host} Auth Bundle",
            site_url=site_url,
            auth_type=AuthType.COOKIE,
            is_shared=True,
            status=AuthStatus.ACTIVE,
            login_selectors={},
        )
        db.add(auth_config)
        await db.flush()
    else:
        if name:
            auth_config.name = name
        auth_config.site_url = site_url
        auth_config.auth_type = AuthType.COOKIE
        auth_config.status = AuthStatus.ACTIVE
        auth_config.is_shared = True if is_x_host(site_host) else bool(auth_config.is_shared)

    _merge_bundle_credentials(auth_config, cookies, storage_state_path, normalized)

    browser_session = None
    if create_browser_session and storage_state_path:
        browser_session = await _upsert_browser_session(db, auth_config, normalized, storage_state_path, len(cookies))

    bound_sources = 0
    if bind_matching_sources:
        if is_x_host(site_host):
            bound_sources = await _bind_bundle_auth_config_to_all_x_sources(db, auth_config)
        else:
            bound_sources = await _bind_bundle_auth_config_to_matching_sources(db, auth_config)

    await db.commit()
    await db.refresh(auth_config)
    if browser_session is not None:
        await db.refresh(browser_session)

    return {
        "auth_config": auth_config,
        "browser_session": browser_session,
        "site_host": site_host,
        "cookie_count": len(cookies),
        "storage_state_imported": bool(storage_state_path),
        "storage_state_path": storage_state_path,
        "bound_sources": bound_sources,
    }


async def _find_matching_auth_config(db: AsyncSession, site_host: str) -> AuthConfig | None:
    result = await db.execute(select(AuthConfig).order_by(AuthConfig.updated_at.desc()))
    for config in result.scalars().all():
        if host_matches(site_host, normalize_host(config.site_url)):
            return config
    return None


async def _bind_bundle_auth_config_to_matching_sources(db: AsyncSession, config: AuthConfig) -> int:
    """Bind imported credentials to every same-host website source.

    The generic binding helper is intentionally conservative and only updates
    sources that already asked for auth. Importing an Auth Bundle is explicit
    operator intent, so same-host website sources should become auth-enabled.
    """
    auth_host = normalize_host(config.site_url)
    if not auth_host:
        return 0
    result = await db.execute(select(Source).where(Source.type == SourceType.WEBSITE))
    bound = 0
    for source in result.scalars().all():
        if not host_matches(normalize_host(source.url), auth_host):
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


async def _bind_bundle_auth_config_to_all_x_sources(db: AsyncSession, config: AuthConfig) -> int:
    """Bind an imported X Auth Bundle to every X source."""
    if not is_x_host(normalize_host(config.site_url)):
        return 0

    result = await db.execute(select(Source).where(Source.type == SourceType.X))
    bound = 0
    for source in result.scalars().all():
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


def _merge_bundle_credentials(
    auth_config: AuthConfig,
    cookies: dict[str, str],
    storage_state_path: str | None,
    bundle: dict[str, Any],
) -> None:
    existing = decrypt_auth_credentials(auth_config)
    existing["cookies"] = cookies
    existing["cookie_mode"] = "bundle"
    existing["cookie_updated_at"] = utcnow_naive().isoformat() + "Z"
    if storage_state_path:
        existing["storage_state_path"] = storage_state_path
        existing["storage_state_mode"] = "bundle"
    existing["auth_bundle"] = {
        "kind": bundle.get("kind"),
        "version": bundle.get("version"),
        "created_at": bundle.get("created_at"),
        "imported_at": utcnow_naive().isoformat() + "Z",
        "site_host": bundle.get("site_host"),
        "captured_with": bundle.get("captured_with") if isinstance(bundle.get("captured_with"), dict) else {},
    }
    auth_config.credentials = encrypt_data(existing)


async def _upsert_browser_session(
    db: AsyncSession,
    auth_config: AuthConfig,
    bundle: dict[str, Any],
    storage_state_path: str,
    cookie_count: int,
) -> BrowserSession:
    site_url = str(bundle.get("site_url") or "")
    site_host = str(bundle.get("site_host") or normalize_host(site_url))
    profile_name = slugify_profile_name(f"bundle-{site_host}")

    result = await db.execute(select(BrowserSession).filter(BrowserSession.site_host == site_host))
    session = result.scalar_one_or_none()
    metadata = {
        "last_bundle_import": {
            "at": utcnow_naive().isoformat() + "Z",
            "bundle_created_at": bundle.get("created_at"),
            "cookie_count": cookie_count,
            "message": "Imported from Auth Bundle; article readability not yet validated.",
        }
    }
    if session is None:
        session = BrowserSession(
            site_url=site_url,
            site_host=site_host,
            profile_name=profile_name,
            user_data_dir=None,
            storage_state_path=storage_state_path,
            session_mode=BrowserSessionMode.STORAGE_STATE.value,
            auth_config_id=auth_config.id,
            status=BrowserSessionStatus.UNVERIFIED,
            last_validated_at=None,
            last_error="Auth Bundle 已导入，需用文章 URL 验证正文可读性后才会标记为有效。",
            metadata_=metadata,
        )
        db.add(session)
        await db.flush()
        return session

    session.site_url = site_url
    session.profile_name = profile_name
    session.user_data_dir = None
    session.storage_state_path = storage_state_path
    session.session_mode = BrowserSessionMode.STORAGE_STATE.value
    session.auth_config_id = auth_config.id
    session.status = BrowserSessionStatus.UNVERIFIED
    session.last_error = "Auth Bundle 已导入，需用文章 URL 验证正文可读性后才会标记为有效。"
    session.last_validated_at = None
    session.metadata_ = metadata
    return session


def _write_storage_state(site_host: str, storage_state: dict[str, Any]) -> str:
    profile_dir = profiles_root() / slugify_profile_name(f"bundle-{site_host}")
    profile_dir.mkdir(parents=True, exist_ok=True)
    path = profile_dir / "storage_state.json"
    path.write_text(json.dumps(storage_state, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return str(path)
