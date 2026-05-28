"""Load model provider catalog from configurable JSON file."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

from app.utils.logger import get_logger

logger = get_logger(__name__)

OLLAMA_DEFAULT_API_BASE = "http://localhost:11434"


def _default_catalog_path() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "model_providers.json"


def load_model_providers() -> List[Dict[str, Any]]:
    """Return model provider definitions from JSON config.

    Env override: MODEL_PROVIDERS_CONFIG_PATH
    """
    raw_path = os.getenv("MODEL_PROVIDERS_CONFIG_PATH")
    candidate_paths: List[Path] = []
    if raw_path:
        candidate_paths.append(Path(raw_path).expanduser())
    default_path = _default_catalog_path()
    if default_path not in candidate_paths:
        candidate_paths.append(default_path)

    providers = None
    for path in candidate_paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Failed to read model providers config {path}: {e}")
            continue

        loaded = payload.get("providers") if isinstance(payload, dict) else None
        if isinstance(loaded, list):
            providers = loaded
            break
        logger.warning(f"Invalid model providers config format in {path}: missing providers list")

    if providers is None:
        return []

    sanitized: List[Dict[str, Any]] = []
    for entry in providers:
        if not isinstance(entry, dict):
            continue
        provider_id = str(entry.get("id") or "").strip()
        name = str(entry.get("name") or "").strip()
        if not provider_id or not name:
            continue
        item = dict(entry)
        models = item.get("models")
        item["models"] = models if isinstance(models, list) else []
        item["requires_api_key"] = bool(item.get("requires_api_key", True))
        item["requires_access_config"] = bool(item.get("requires_access_config", False))
        sanitized.append(item)

    return sanitized


def normalize_api_base(api_base: Any) -> str:
    """Normalize a provider API base without guessing a default."""
    return str(api_base or "").strip().rstrip("/")


def provider_default_api_base(provider: Any) -> str | None:
    """Return the catalog default API base for a provider, if one exists."""
    provider_id = str(provider or "").strip().lower()
    if not provider_id:
        return None
    for entry in load_model_providers():
        if str(entry.get("id") or "").strip().lower() == provider_id:
            base = normalize_api_base(entry.get("default_api_base"))
            return base or None
    return None


def is_ollama_api_base(api_base: Any) -> bool:
    """True when an API base is the default local Ollama endpoint."""
    value = normalize_api_base(api_base)
    if not value:
        return False
    parsed = urlparse(value if "://" in value else f"http://{value}")
    host = (parsed.hostname or "").lower()
    port = parsed.port
    return host in {"localhost", "127.0.0.1", "::1"} and port == 11434


def sanitize_provider_api_base(
    provider: Any,
    api_base: Any,
    *,
    fallback_default: Any = None,
) -> str | None:
    """Return a provider-compatible API base.

    The common footgun is switching ``provider`` from Ollama to a cloud provider
    while leaving ``http://localhost:11434`` in persisted settings. For known
    providers, replace that stale Ollama URL with the catalog default; for custom
    OpenAI-compatible providers, return ``None`` so callers can require an
    explicit endpoint instead of silently using OpenAI's default.
    """
    provider_id = str(provider or "").strip().lower()
    base = normalize_api_base(api_base)
    catalog_default = provider_default_api_base(provider_id)
    fallback = normalize_api_base(fallback_default)

    if not base:
        return catalog_default or fallback or None
    if provider_id != "ollama" and is_ollama_api_base(base):
        if catalog_default:
            return catalog_default
        if fallback and not is_ollama_api_base(fallback):
            return fallback
        return None
    return base
