"""API routes for system settings and model discovery."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.provider import list_ollama_models
from app.database import get_async_db
from app.models.auth_config import APIConfig, AuthStatus
from app.services.system_settings import (
    get_system_settings_async,
    get_system_settings_for_response,
    update_system_settings_async,
)
from app.api.configs_common import decrypt_api_credentials
from app.utils.model_catalog import load_model_providers

router = APIRouter()


def _normalize_api_base(api_base: str) -> str:
    return (api_base or "").rstrip("/")


async def _fetch_ollama_models(api_base: str) -> List[dict]:
    """Fetch installed Ollama models from /api/tags."""
    names = await list_ollama_models(_normalize_api_base(api_base))
    return [{"id": name, "name": name} for name in names]


@router.get("/settings")
async def get_system_settings(db: AsyncSession = Depends(get_async_db)):
    """Get system settings from persistent storage."""
    settings = await get_system_settings_async(db)
    return get_system_settings_for_response(settings)


@router.patch("/settings")
async def update_system_settings(
    settings_data: dict,
    db: AsyncSession = Depends(get_async_db),
):
    """Update and persist system settings."""
    updated = await update_system_settings_async(db, settings_data)
    return get_system_settings_for_response(updated)


@router.get("/ai-models/available")
async def get_available_models(
    include_unconfigured: bool = False,
    db: AsyncSession = Depends(get_async_db),
):
    """Get list of available AI models."""
    runtime_settings = await get_system_settings_async(db)
    configured_base = (runtime_settings.get("ai_model") or {}).get("api_base") or "http://localhost:11434"
    translation_base = (runtime_settings.get("translation_model") or {}).get("api_base") or configured_base

    candidate_bases = []
    for base in [configured_base, translation_base, "http://localhost:11434", "http://localhost:11434"]:
        normalized = _normalize_api_base(base)
        if normalized and normalized not in candidate_bases:
            candidate_bases.append(normalized)

    ollama_models: List[dict] = []
    resolved_base = configured_base
    availability_message = ""
    for base in candidate_bases:
        models = await _fetch_ollama_models(base)
        if models:
            ollama_models = models
            resolved_base = base
            break

    if not ollama_models:
        availability_message = (
            "未检测到可用的 Ollama 本地模型。请确认 Ollama 正在运行，且已安装所需模型。"
        )

    providers = load_model_providers()
    ollama_provider = next((p for p in providers if p.get("id") == "ollama"), None)
    if ollama_provider:
        ollama_provider["models"] = ollama_models
        ollama_provider["requires_api_key"] = False
        ollama_provider["default_api_base"] = resolved_base
        ollama_provider["model_source"] = "installed" if ollama_models else "unavailable"
        if availability_message:
            ollama_provider["availability_message"] = availability_message
    else:
        providers.append(
            {
                "id": "ollama",
                "name": "Ollama (本地)",
                "models": ollama_models,
                "requires_api_key": False,
                "default_api_base": resolved_base,
                "model_source": "installed" if ollama_models else "unavailable",
                "availability_message": availability_message or None,
            }
        )

    if not include_unconfigured:
        result = await db.execute(select(APIConfig).filter(APIConfig.status == AuthStatus.ACTIVE))
        rows = result.scalars().all()
        configured_platforms = {row.platform for row in rows if row and row.platform}
        api_base_map: dict[str, str] = {}
        for row in rows:
            creds = decrypt_api_credentials(row)
            additional = creds.get("additional") or {}
            api_base = additional.get("api_base")
            if api_base and row.platform not in api_base_map:
                api_base_map[row.platform] = api_base

        settings_provider = (runtime_settings.get("ai_model") or {}).get("provider")
        settings_api_key = (runtime_settings.get("ai_model") or {}).get("api_key")
        if settings_provider and settings_api_key:
            configured_platforms.add(settings_provider)

        trans_provider = (runtime_settings.get("translation_model") or {}).get("provider")
        trans_api_key = (runtime_settings.get("translation_model") or {}).get("api_key")
        if trans_provider and trans_api_key:
            configured_platforms.add(trans_provider)

        providers = [
            p for p in providers if (not p.get("requires_api_key")) or (p["id"] in configured_platforms)
        ]
        for p in providers:
            api_base = api_base_map.get(p["id"])
            if api_base:
                p["default_api_base"] = api_base

    return {"providers": providers}
