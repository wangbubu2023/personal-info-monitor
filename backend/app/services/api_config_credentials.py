"""Compatibility shim for platform auth API-config credential enrichment."""

from app.platform.auth.api_config_credentials import (  # noqa: F401
    _fetch_first_api_config,
    enrich_model_settings_from_api_config,
)

__all__ = [
    "_fetch_first_api_config",
    "enrich_model_settings_from_api_config",
]
