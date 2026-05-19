"""Unified provider runtime resolution and text generation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

import httpx

from app.config import get_settings
from app.services.api_config_credentials import enrich_model_settings_from_api_config
from app.services.system_settings import get_system_settings_sync
from app.utils.logger import get_logger

logger = get_logger(__name__)

_token_meter_day: date | None = None
_token_meter_total: int = 0


def _reset_token_meter_if_needed() -> None:
    global _token_meter_day, _token_meter_total

    today = date.today()
    if _token_meter_day != today:
        _token_meter_day = today
        _token_meter_total = 0


def _reserve_ai_token_budget(estimated_tokens: int) -> bool:
    """Return False when the rough daily budget would be exceeded."""
    settings = get_settings()
    cap = int(settings.ai_daily_token_budget or 0)
    if cap <= 0:
        return True
    _reset_token_meter_if_needed()
    global _token_meter_total
    est = max(1, min(estimated_tokens, cap))
    if _token_meter_total + est > cap:
        logger.warning(
            "AI daily token budget exceeded (used≈%s + est=%s > cap=%s)",
            _token_meter_total,
            est,
            cap,
        )
        return False
    _token_meter_total += est
    return True


@dataclass
class ModelRuntime:
    """Normalized model runtime config."""

    provider: str
    model: str
    api_base: Optional[str] = None
    api_key: Optional[str] = None
    temperature: float = 0.2
    max_tokens: int = 1000


def _coerce_float(value, default: float, *, min_value: float, max_value: float) -> float:
    try:
        parsed = float(value)
    except Exception:
        return default
    return max(min_value, min(max_value, parsed))


def _coerce_int(value, default: int, *, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        return default
    return max(min_value, min(max_value, parsed))


def normalize_provider(provider: Optional[str], default_provider: str = "ollama") -> str:
    normalized = str(provider or "").strip().lower()
    return normalized or default_provider


def _provider_catalog_default_api_base(provider: str) -> Optional[str]:
    """Look up ``default_api_base`` for *provider* from ``model_providers.json``.

    Returns ``None`` when the provider is unknown or its entry has no
    default base. Used so users can save a provider row without pasting the
    endpoint and still get a sane URL at runtime (e.g. MiniMax → api.minimaxi.com/v1).
    """
    try:
        from app.utils.model_catalog import load_model_providers
    except Exception:
        return None
    plat = (provider or "").strip().lower()
    if not plat:
        return None
    try:
        for entry in load_model_providers():
            if str(entry.get("id") or "").strip().lower() == plat:
                base = str(entry.get("default_api_base") or "").strip().rstrip("/")
                return base or None
    except Exception:
        return None
    return None


def normalize_model_runtime(
    model_settings: dict,
    *,
    default_provider: str = "ollama",
    default_model: str = "",
    default_api_base: Optional[str] = None,
    default_temperature: float = 0.2,
    default_max_tokens: int = 1000,
    fallback_api_key: Optional[str] = None,
) -> ModelRuntime:
    """Build runtime from raw model settings."""
    provider = normalize_provider(model_settings.get("provider"), default_provider=default_provider)
    model = str(model_settings.get("model") or "").strip() or default_model
    raw_api_base = str(model_settings.get("api_base") or "").strip()
    if not raw_api_base:
        # Prefer the provider's catalog default (e.g. MiniMax → api.minimaxi.com/v1)
        # over the caller-supplied ``default_api_base`` which is typically Ollama's
        # localhost URL. Falling back to ``default_api_base`` only when the provider
        # is unknown keeps Ollama working without registering it in the catalog.
        raw_api_base = _provider_catalog_default_api_base(provider) or (default_api_base or "")
    api_base = raw_api_base or None
    api_key = str(model_settings.get("api_key") or "").strip() or fallback_api_key
    temperature = _coerce_float(model_settings.get("temperature"), default_temperature, min_value=0.0, max_value=2.0)
    max_tokens = _coerce_int(model_settings.get("max_tokens"), default_max_tokens, min_value=1, max_value=16000)
    return ModelRuntime(
        provider=provider,
        model=model,
        api_base=api_base,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def _normalize_api_base(api_base: Optional[str], default: str = "http://localhost:11434") -> str:
    value = str(api_base or "").strip().rstrip("/")
    return value or default


async def list_ollama_models(api_base: Optional[str]) -> list[str]:
    """Return installed Ollama model names from /api/tags."""
    base = _normalize_api_base(api_base)
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(f"{base}/api/tags")
        if resp.status_code != 200:
            return []
        seen: set[str] = set()
        models: list[str] = []
        for item in resp.json().get("models") or []:
            name = str((item or {}).get("name") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            models.append(name)
        return models
    except Exception:
        return []


async def _resolve_ollama_runtime(runtime: ModelRuntime, *, default_model: str = "") -> Optional[ModelRuntime]:
    runtime.api_base = _normalize_api_base(runtime.api_base)
    model_names = await list_ollama_models(runtime.api_base)
    if not model_names:
        return None
    preferred = runtime.model or default_model
    runtime.model = preferred if preferred in model_names else model_names[0]
    return runtime


async def get_runtime_from_system_settings(
    *,
    setting_key: str,
    default_provider: str,
    default_model: str,
    default_api_base: Optional[str] = None,
    default_temperature: float = 0.2,
    default_max_tokens: int = 1000,
) -> Optional[ModelRuntime]:
    """Resolve runtime from persistent system settings and verify availability."""
    settings = get_settings()
    runtime_settings = get_system_settings_sync() or {}
    model_settings = (runtime_settings.get(setting_key) or {}) if isinstance(runtime_settings, dict) else {}
    if not isinstance(model_settings, dict):
        model_settings = {}
    model_settings = enrich_model_settings_from_api_config(model_settings)

    runtime = normalize_model_runtime(
        model_settings,
        default_provider=default_provider,
        default_model=default_model,
        default_api_base=default_api_base,
        default_temperature=default_temperature,
        default_max_tokens=default_max_tokens,
        fallback_api_key=getattr(settings, "openai_api_key", None),
    )

    if runtime.provider == "ollama":
        return await _resolve_ollama_runtime(runtime, default_model=default_model)

    if not runtime.model:
        return None

    if runtime.provider == "openai" and not runtime.api_key:
        return None

    # Other providers currently use OpenAI-compatible chat APIs.
    if runtime.provider not in {"openai", "ollama"} and not runtime.api_key:
        return None

    return runtime


class ModelProviderClient:
    """Unified text generation client for Ollama and OpenAI-compatible providers."""

    async def generate_text(
        self,
        runtime: ModelRuntime,
        *,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout_seconds: float = 180.0,
    ) -> str:
        settings = get_settings()
        if not settings.ai_processing_enabled:
            logger.info("AI processing disabled (ai_processing_enabled=false); skipping LLM call")
            return ""
        mt = max_tokens if max_tokens is not None else runtime.max_tokens
        rough = len(prompt) // 4 + len(system_prompt or "") // 4 + int(mt or 500)
        if not _reserve_ai_token_budget(rough):
            return ""

        provider = runtime.provider
        if provider == "ollama":
            return await self._generate_with_ollama(
                runtime,
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                timeout_seconds=timeout_seconds,
            )
        return await self._generate_with_openai_compatible(
            runtime,
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def _generate_with_ollama(
        self,
        runtime: ModelRuntime,
        *,
        prompt: str,
        system_prompt: Optional[str],
        temperature: Optional[float],
        timeout_seconds: float,
    ) -> str:
        api_base = _normalize_api_base(runtime.api_base)
        temp = runtime.temperature if temperature is None else temperature
        merged_prompt = prompt
        if system_prompt:
            merged_prompt = f"{system_prompt}\n\n{prompt}"

        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            try:
                resp = await client.post(
                    f"{api_base}/api/generate",
                    json={
                        "model": runtime.model,
                        "prompt": merged_prompt,
                        "stream": False,
                        "options": {
                            "temperature": temp,
                        },
                    },
                )
                if resp.status_code == 200:
                    text = str((resp.json() or {}).get("response") or "").strip()
                    if text:
                        return text
            except Exception:
                logger.debug("Ollama /api/generate failed, fallback to chat endpoint", exc_info=True)

            chat_resp = await client.post(
                f"{api_base}/v1/chat/completions",
                json={
                    "model": runtime.model,
                    "messages": [
                        {"role": "system", "content": system_prompt or "You are a helpful assistant."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": temp,
                },
            )
            chat_resp.raise_for_status()
            choices = (chat_resp.json() or {}).get("choices") or [{}]
            message = (choices[0].get("message") or {}).get("content")
            return str(message or "").strip()

    async def _generate_with_openai_compatible(
        self,
        runtime: ModelRuntime,
        *,
        prompt: str,
        system_prompt: Optional[str],
        temperature: Optional[float],
        max_tokens: Optional[int],
    ) -> str:
        if not runtime.api_key:
            return ""

        import openai

        kwargs = {"api_key": runtime.api_key}
        if runtime.api_base:
            kwargs["base_url"] = runtime.api_base
        client = openai.AsyncOpenAI(**kwargs)
        resp = await client.chat.completions.create(
            model=runtime.model,
            messages=[
                {"role": "system", "content": system_prompt or "You are a helpful assistant."},
                {"role": "user", "content": prompt},
            ],
            temperature=(runtime.temperature if temperature is None else temperature),
            max_tokens=(runtime.max_tokens if max_tokens is None else max_tokens),
        )
        content = (resp.choices[0].message.content or "").strip()
        return content
