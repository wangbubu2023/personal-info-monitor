"""Merge model API credentials from api_configs into runtime model dicts."""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.database import SessionLocal
from app.models.auth_config import APIConfig, AuthStatus
from app.platform.auth.api_credentials import decrypt_api_credentials
from app.utils.logger import get_logger
from app.utils.model_catalog import sanitize_provider_api_base

logger = get_logger(__name__)


def _fetch_first_api_config(platform: str) -> Optional[APIConfig]:
    plat = (platform or "").strip().lower()
    if not plat:
        return None
    db = SessionLocal()
    try:
        return (
            db.query(APIConfig)
            .filter(APIConfig.platform == plat, APIConfig.status == AuthStatus.ACTIVE)
            .order_by(APIConfig.created_at.asc())
            .first()
        )
    except Exception as exc:  # noqa: BLE001 - DB lookup failure should not break model fallback
        logger.debug("api_config lookup failed for %s: %s", plat, exc)
        return None
    finally:
        db.close()


def enrich_model_settings_from_api_config(model_settings: Dict[str, Any] | None) -> Dict[str, Any]:
    """Fill api_base / api_key from the active api_configs row for this provider.

    When a row exists, its values take precedence so the model-access
    credential store remains the single source for endpoints and keys;
    legacy values in system_settings are only used if no row exists.
    """
    if not isinstance(model_settings, dict):
        return {}
    out = dict(model_settings)
    provider = str(out.get("provider") or "").strip().lower()
    if not provider:
        return out

    row = _fetch_first_api_config(provider)
    if not row:
        return out

    try:
        creds = decrypt_api_credentials(row)
    except Exception:  # noqa: BLE001 - credential decrypt fallback preserves legacy behaviour
        return out

    additional = creds.get("additional") or {}
    cfg_base = additional.get("api_base")
    cfg_key = creds.get("api_key")

    resolved_base = sanitize_provider_api_base(provider, cfg_base or out.get("api_base"))
    if resolved_base:
        out["api_base"] = resolved_base
    else:
        out.pop("api_base", None)
    if provider != "ollama" and cfg_key:
        out["api_key"] = str(cfg_key).strip()

    return out


__all__ = [
    "_fetch_first_api_config",
    "enrich_model_settings_from_api_config",
]
