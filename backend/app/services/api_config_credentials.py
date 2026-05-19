"""Merge model API credentials from api_configs (模型接入) into runtime model dicts."""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.api.configs_common import decrypt_api_credentials
from app.database import SessionLocal
from app.models.auth_config import APIConfig, AuthStatus
from app.utils.logger import get_logger

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
    except Exception as exc:
        logger.debug("api_config lookup failed for %s: %s", plat, exc)
        return None
    finally:
        db.close()


def enrich_model_settings_from_api_config(model_settings: Dict[str, Any] | None) -> Dict[str, Any]:
    """Fill api_base / api_key from the active api_configs row for this provider.

    When a row exists, its values take precedence so「模型接入」remains the single source
    for endpoints and keys; legacy values in system_settings are only used if no row exists.
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
    except Exception:
        return out

    additional = creds.get("additional") or {}
    cfg_base = additional.get("api_base")
    cfg_key = creds.get("api_key")

    if cfg_base:
        out["api_base"] = str(cfg_base).strip().rstrip("/")
    if provider != "ollama" and cfg_key:
        out["api_key"] = str(cfg_key).strip()

    return out
