"""API routes for API key and auth configuration management."""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_async_db
from app.models.auth_config import APIConfig, AuthConfig, AuthStatus, AuthType
from app.models.browser_session import BrowserSession
from app.models.source import Source
from app.schemas.config import (
    APIConfigCreate,
    APIConfigUpdate,
    AuthConfigCreate,
    AuthConfigUpdate,
)
from app.utils.datetime import utcnow_naive
from app.platform.security.encryption import decrypt_data, encrypt_data
from app.utils.url import normalize_host
from app.api.configs_common import (
    bind_auth_config_to_all_x_sources,
    bind_auth_config_to_sources,
    normalize_cookies_input,
    serialize_api_config,
    serialize_auth_config,
)

router = APIRouter()


@dataclass(frozen=True)
class _DecodedCredentials:
    """Result of decrypting stored credentials."""

    data: dict
    decrypt_failed: bool = False


def _load_existing_credentials(encrypted_payload: str | None) -> _DecodedCredentials:
    """Decode encrypted credential payloads; distinguish failure from empty."""
    if not encrypted_payload:
        return _DecodedCredentials({})
    try:
        raw_creds = decrypt_data(encrypted_payload)
        if isinstance(raw_creds, dict):
            return _DecodedCredentials(raw_creds)
        if isinstance(raw_creds, str):
            parsed = json.loads(raw_creds)
            return _DecodedCredentials(parsed if isinstance(parsed, dict) else {})
    except Exception:
        from app.utils.logger import get_logger

        get_logger(__name__).exception("Failed to decrypt stored credentials")
        return _DecodedCredentials({}, decrypt_failed=True)
    return _DecodedCredentials({})


def _apply_cookie_update(
    credentials: dict,
    cookies,
    *,
    site_host: str | None,
) -> None:
    if cookies is None:
        return
    try:
        parsed = normalize_cookies_input(cookies, site_host=site_host)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if parsed:
        credentials["cookies"] = parsed
        credentials["cookie_mode"] = "manual"
        credentials["cookie_updated_at"] = utcnow_naive().isoformat() + "Z"
        return

    credentials.pop("cookies", None)
    credentials.pop("cookie_mode", None)
    credentials.pop("cookie_updated_at", None)


def _merge_api_credentials(config, config_data: APIConfigUpdate) -> None:
    load = _load_existing_credentials(config.encrypted_credentials)
    if load.decrypt_failed:
        raise HTTPException(
            status_code=503,
            detail="Stored credentials could not be decrypted (encryption key mismatch?). "
            "Fix PIM_ENCRYPTION_KEY / runtime-secrets.json before updating this entry.",
        )
    existing_creds = load.data
    if config_data.api_key is not None:
        existing_creds["api_key"] = config_data.api_key
    if config_data.api_secret is not None:
        existing_creds["api_secret"] = config_data.api_secret
    if config_data.additional_config is not None:
        existing_creds["additional"] = config_data.additional_config
    config.encrypted_credentials = encrypt_data(existing_creds)


def _merge_auth_credentials(config, config_data: AuthConfigUpdate) -> None:
    load = _load_existing_credentials(config.credentials)
    if load.decrypt_failed:
        raise HTTPException(
            status_code=503,
            detail="Stored credentials could not be decrypted (encryption key mismatch?). "
            "Fix encryption key before updating this auth config.",
        )
    existing_creds = load.data
    if config_data.username is not None:
        existing_creds["username"] = config_data.username
    if config_data.password is not None:
        existing_creds["password"] = config_data.password
    _apply_cookie_update(
        existing_creds,
        config_data.cookies,
        site_host=normalize_host(config.site_url),
    )
    config.credentials = encrypt_data(existing_creds) if existing_creds else None


@router.get("/api-keys")
async def list_api_configs(db: AsyncSession = Depends(get_async_db)):
    """List all API configurations."""
    result = await db.execute(select(APIConfig).order_by(APIConfig.platform))
    configs = result.scalars().all()
    return [serialize_api_config(c) for c in configs]


@router.post("/api-keys")
async def create_api_config(
    config_data: APIConfigCreate,
    db: AsyncSession = Depends(get_async_db),
):
    """Create a new API configuration."""
    credentials = {"api_key": (config_data.api_key or "").strip()}
    if config_data.api_secret:
        credentials["api_secret"] = config_data.api_secret
    if config_data.additional_config:
        credentials["additional"] = config_data.additional_config

    config = APIConfig(
        platform=config_data.platform,
        name=config_data.name,
        encrypted_credentials=encrypt_data(credentials),
        status=AuthStatus.ACTIVE,
    )

    db.add(config)
    await db.commit()
    await db.refresh(config)
    return serialize_api_config(config)


@router.get("/api-keys/{config_id}")
async def get_api_config(
    config_id: UUID,
    db: AsyncSession = Depends(get_async_db),
):
    """Get a specific API configuration."""
    result = await db.execute(select(APIConfig).filter(APIConfig.id == config_id))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="API config not found")
    return serialize_api_config(config)


@router.patch("/api-keys/{config_id}")
async def update_api_config(
    config_id: UUID,
    config_data: APIConfigUpdate,
    db: AsyncSession = Depends(get_async_db),
):
    """Update an API configuration."""
    result = await db.execute(select(APIConfig).filter(APIConfig.id == config_id))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="API config not found")

    if config_data.name is not None:
        config.name = config_data.name

    if (
        config_data.api_key is not None
        or config_data.api_secret is not None
        or config_data.additional_config is not None
    ):
        _merge_api_credentials(config, config_data)

    await db.commit()
    await db.refresh(config)
    return serialize_api_config(config)


@router.delete("/api-keys/{config_id}")
async def delete_api_config(
    config_id: UUID,
    db: AsyncSession = Depends(get_async_db),
):
    """Delete an API configuration."""
    result = await db.execute(select(APIConfig).filter(APIConfig.id == config_id))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="API config not found")

    await db.delete(config)
    await db.commit()
    return {"message": "API config deleted successfully"}


@router.get("/auth-configs")
async def list_auth_configs(db: AsyncSession = Depends(get_async_db)):
    """List all authentication configurations."""
    result = await db.execute(
        select(AuthConfig)
        .options(selectinload(AuthConfig.sources))
        .order_by(AuthConfig.site_url, AuthConfig.name)
    )
    configs = result.scalars().all()
    return [serialize_auth_config(c) for c in configs]


@router.post("/auth-configs")
async def create_auth_config(
    config_data: AuthConfigCreate,
    db: AsyncSession = Depends(get_async_db),
):
    """Create a new authentication configuration."""
    credentials = {}
    if config_data.username:
        credentials["username"] = config_data.username
    if config_data.password:
        credentials["password"] = config_data.password
    if config_data.cookies is not None:
        _apply_cookie_update(
            credentials,
            config_data.cookies,
            site_host=normalize_host(config_data.site_url),
        )

    config = AuthConfig(
        name=config_data.name,
        site_url=config_data.site_url,
        auth_type=AuthType(config_data.auth_type),
        is_shared=bool(config_data.is_shared),
        credentials=encrypt_data(credentials) if credentials else None,
        login_url=config_data.login_url,
        login_selectors=config_data.login_selectors or {},
        status=AuthStatus.ACTIVE,
    )

    db.add(config)
    await db.flush()
    bound_sources = await bind_auth_config_to_sources(db, config)
    if config_data.bind_all_x_sources:
        bound_sources += await bind_auth_config_to_all_x_sources(db, config)
    await db.commit()
    result = await db.execute(
        select(AuthConfig).options(selectinload(AuthConfig.sources)).filter(AuthConfig.id == config.id)
    )
    config = result.scalar_one()

    payload = serialize_auth_config(config)
    payload["bound_sources"] = bound_sources
    return payload


@router.get("/auth-configs/{config_id}")
async def get_auth_config(
    config_id: UUID,
    db: AsyncSession = Depends(get_async_db),
):
    """Get a specific authentication configuration."""
    result = await db.execute(
        select(AuthConfig).options(selectinload(AuthConfig.sources)).filter(AuthConfig.id == config_id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Auth config not found")
    return serialize_auth_config(config)


@router.patch("/auth-configs/{config_id}")
async def update_auth_config(
    config_id: UUID,
    config_data: AuthConfigUpdate,
    db: AsyncSession = Depends(get_async_db),
):
    """Update an authentication configuration."""
    result = await db.execute(select(AuthConfig).filter(AuthConfig.id == config_id))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Auth config not found")

    if config_data.name is not None:
        config.name = config_data.name
    if config_data.site_url is not None:
        config.site_url = config_data.site_url
    if config_data.auth_type is not None:
        config.auth_type = AuthType(config_data.auth_type)
    if config_data.is_shared is not None:
        config.is_shared = config_data.is_shared
    if config_data.login_url is not None:
        config.login_url = config_data.login_url
    if config_data.login_selectors is not None:
        config.login_selectors = config_data.login_selectors

    if (
        config_data.username is not None
        or config_data.password is not None
        or config_data.cookies is not None
    ):
        _merge_auth_credentials(config, config_data)

    bound_sources = await bind_auth_config_to_sources(db, config)
    if config_data.bind_all_x_sources:
        bound_sources += await bind_auth_config_to_all_x_sources(db, config)
    await db.commit()
    result = await db.execute(
        select(AuthConfig).options(selectinload(AuthConfig.sources)).filter(AuthConfig.id == config_id)
    )
    config = result.scalar_one()

    payload = serialize_auth_config(config)
    payload["bound_sources"] = bound_sources
    return payload


@router.delete("/auth-configs/{config_id}")
async def delete_auth_config(
    config_id: UUID,
    db: AsyncSession = Depends(get_async_db),
):
    """Delete an authentication configuration.

    When the config is still referenced by monitoring sources or browser
    sessions, a plain ``DELETE`` would blow up on the FK constraint. Instead of
    refusing the request (and leaving users with no path forward through the
    UI), we unlink those referencing rows first and report the counts back, so
    the caller knows exactly what was cleaned up. This mirrors the "legacy
    cleanup" intent exposed in the frontend.
    """
    config_id_str = str(config_id)
    result = await db.execute(select(AuthConfig).filter(AuthConfig.id == config_id))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Auth config not found")

    src_result = await db.execute(
        update(Source)
        .where(Source.auth_config_id == config_id_str)
        .values(auth_config_id=None, auth_required=False)
    )
    sources_unlinked = src_result.rowcount or 0

    session_result = await db.execute(
        update(BrowserSession)
        .where(BrowserSession.auth_config_id == config_id_str)
        .values(auth_config_id=None)
    )
    sessions_unlinked = session_result.rowcount or 0

    await db.delete(config)
    await db.commit()
    return {
        "message": "Auth config deleted successfully",
        "sources_unlinked": sources_unlinked,
        "browser_sessions_unlinked": sessions_unlinked,
    }
