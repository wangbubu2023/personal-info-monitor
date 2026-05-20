"""Credential (API-key + AuthConfig) helpers shared across config routes.

Split out of the former monolithic ``configs_common.py`` (audit 2026-04-20,
§8.2 Q1). This module owns everything that decrypts or serialises opaque
credential blobs; cookie / browser-session logic lives in sibling modules.
"""

from __future__ import annotations

import json

from app.models.auth_config import APIConfig, AuthConfig
from app.platform.auth.api_credentials import decrypt_api_credentials  # noqa: F401 - re-export
from app.utils.datetime import to_iso_z
from app.platform.security.encryption import decrypt_data
from app.utils.url import normalize_host


def mask_api_key(key: str) -> str:
    if not key or len(key) < 8:
        return "****"
    return f"{key[:4]}...{key[-4:]}"


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
    except Exception:  # noqa: BLE001 - opaque decrypt / JSON path, UI degrades to "no creds"
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
    cookies = credentials.get("cookies") if isinstance(credentials.get("cookies"), dict) else {}
    username = str(credentials.get("username") or "").strip() or None
    cookie_mode = str(credentials.get("cookie_mode") or "").strip() or None
    cookie_updated_at = str(credentials.get("cookie_updated_at") or "").strip() or None

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
        "saved_username": username,
        "has_password": bool(str(credentials.get("password") or "").strip()),
        "has_cookies": bool(cookies),
        "cookie_count": len(cookies),
        "cookie_mode": cookie_mode,
        "cookie_updated_at": cookie_updated_at,
    }


def is_shared_x_cookie_config(config: AuthConfig) -> bool:
    """Whether the auth config is a reusable X cookie profile."""
    host = normalize_host(config.site_url)
    auth_type = config.auth_type.value if hasattr(config.auth_type, "value") else str(config.auth_type or "").lower()
    return bool(config.is_shared) and auth_type == "cookie" and host in {"x.com", "twitter.com"}
