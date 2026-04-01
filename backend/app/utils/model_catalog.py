"""Load model provider catalog from configurable JSON file."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

from app.utils.logger import get_logger

logger = get_logger(__name__)


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
        sanitized.append(item)

    return sanitized
