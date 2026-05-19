"""fetch-domain glue between persisted ``BrowserSession`` rows and other ORM state.

These helpers take the *output* of a Playwright bootstrap (cookie list,
session row) and reconcile it with the rest of the database:

* ``serialize_browser_session`` — JSON-friendly view for the API.
* ``ensure_x_shared_auth_config`` — find or create the single shared X cookie
  config that every X source will point at.
* ``sync_cookies_to_auth_config`` — write host-matching cookies from a browser
  context into the linked ``AuthConfig`` (encrypted blob).
* ``bind_browser_session_to_sources`` — point every matching source at a
  freshly-bootstrapped session (website sources via ``metadata_``, X sources
  via ``auth_config_id`` so the existing collector path keeps working).

Playwright orchestration itself lives in ``app.platform.browser``; this
module never touches Chromium directly.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Source
from app.models.auth_config import AuthConfig
from app.models.browser_session import BrowserSession
from app.platform.browser.hosts import _X_HOSTS, is_x_host
from app.utils.datetime import to_iso_z, utcnow_naive
from app.utils.encryption import encrypt_data
from app.utils.logger import get_logger
from app.utils.url import host_matches, normalize_host

logger = get_logger(__name__)


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
            # X 抓取依赖 auth_config.credentials.cookies；把 X 源统一指向浏览器
            # 会话关联的那份 auth_config，cookie 同步完成后即可直接使用。
            if source.auth_config_id == session.auth_config_id:
                continue
            source.auth_config_id = session.auth_config_id
            source.auth_required = True
            bound += 1
    return bound
