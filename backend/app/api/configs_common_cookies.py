"""Cookie + source-binding helpers extracted from the old configs_common.py.

Covers cookie-shape normalization, cookie extraction for a given host, and
the source-binding routines that attach an ``AuthConfig`` to the matching
Source rows.
"""

from __future__ import annotations

from typing import Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Source
from app.models.auth_config import AuthConfig
from app.models.source import SourceType
from app.utils.cookies import normalize_cookie_dict
from app.utils.url import host_matches, normalize_host

from app.api.configs_common_auth import (
    decrypt_auth_credentials,
    is_shared_x_cookie_config,
)


def normalize_cookies_input(cookies, *, site_host: str | None = None) -> dict:
    """Parse user-supplied cookies into a canonical ``{name: value}`` dict.

    Accepts dicts, cookie-header strings, and empty values. Empty input
    returns ``{}``; invalid input raises ``ValueError`` with a
    human-readable hint.
    """
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


def extract_auth_cookies_for_host(config: Optional[AuthConfig], site_host: str) -> Dict[str, str]:
    if not config:
        return {}
    credentials = decrypt_auth_credentials(config)
    cookies = credentials.get("cookies") if isinstance(credentials.get("cookies"), dict) else {}
    normalized = normalize_cookie_dict(cookies, site_host=site_host)
    return normalized if normalized else {}


async def bind_auth_config_to_sources(db: AsyncSession, config: AuthConfig) -> int:
    """Bind auth config to matching website sources, ensuring persistence on source rows."""
    auth_host = normalize_host(config.site_url)
    if not auth_host:
        return 0

    like_host = f"%{auth_host}%"
    result = await db.execute(
        select(Source).where(
            Source.type == SourceType.WEBSITE,
            Source.url.ilike(like_host),
        )
    )
    sources = result.scalars().all()
    bound = 0

    for source in sources:
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


async def bind_auth_config_to_all_x_sources(db: AsyncSession, config: AuthConfig) -> int:
    """Bind a shared X cookie profile to every X source."""
    if not is_shared_x_cookie_config(config):
        return 0

    result = await db.execute(select(Source).where(Source.type == SourceType.X))
    sources = result.scalars().all()
    bound = 0

    for source in sources:
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
