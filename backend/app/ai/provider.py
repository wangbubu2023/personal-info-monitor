"""Unified provider runtime resolution and text generation helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from app.platform.config.settings import get_settings
from app.platform.auth.api_config_credentials import enrich_model_settings_from_api_config
from app.platform.config.system_settings import get_system_settings_sync
from app.utils.ai_budget import reserve_ai_token_budget
from app.utils.model_catalog import sanitize_provider_api_base
from app.utils.logger import get_logger

logger = get_logger(__name__)

OLLAMA_NUM_CTX_TRANSLATION_DEFAULT = 2048
OLLAMA_NUM_CTX_WRITING_DEFAULT = 8192
OLLAMA_KEEP_ALIVE = "30m"
OLLAMA_NUM_CTX_MIN = 1024
OLLAMA_NUM_CTX_MAX = 262144
OLLAMA_NUM_CTX_OPTIONS = (
    1024,
    2048,
    4096,
    8192,
    16384,
    32768,
    65536,
    131072,
    262144,
)

def _reserve_ai_token_budget(estimated_tokens: int) -> bool:
    """Return False when a persistent daily/monthly budget would be exceeded."""
    reservation = reserve_ai_token_budget(estimated_tokens)
    if not reservation.allowed:
        logger.warning(
            "AI token budget exceeded (%s): daily=%s/%s monthly=%s/%s est=%s",
            reservation.reason,
            reservation.daily_used,
            reservation.daily_cap,
            reservation.monthly_used,
            reservation.monthly_cap,
            reservation.estimated_tokens,
        )
    return reservation.allowed


@dataclass
class ModelRuntime:
    """Normalized model runtime config."""

    provider: str
    model: str
    api_base: Optional[str] = None
    api_key: Optional[str] = None
    temperature: float = 0.2
    max_tokens: int = 1000
    ollama_num_ctx: int = OLLAMA_NUM_CTX_TRANSLATION_DEFAULT
    ollama_no_think: bool = False


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


def _parse_bool_setting(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value) and value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("1", "true", "yes", "on"):
            return True
        if normalized in ("0", "false", "no", "off"):
            return False
    return default


def snap_ollama_num_ctx(value: int) -> int:
    if value in OLLAMA_NUM_CTX_OPTIONS:
        return value
    return min(OLLAMA_NUM_CTX_OPTIONS, key=lambda option: abs(option - value))


def resolve_ollama_num_ctx(model_settings: dict, *, default: int) -> int:
    if not isinstance(model_settings, dict):
        return snap_ollama_num_ctx(default)
    if "ollama_num_ctx" not in model_settings:
        return snap_ollama_num_ctx(default)
    coerced = _coerce_int(
        model_settings.get("ollama_num_ctx"),
        default,
        min_value=OLLAMA_NUM_CTX_MIN,
        max_value=OLLAMA_NUM_CTX_MAX,
    )
    return snap_ollama_num_ctx(coerced)


def resolve_ollama_no_think(model_settings: dict, *, default: bool) -> bool:
    if not isinstance(model_settings, dict):
        return default
    if "ollama_no_think" not in model_settings:
        return default
    return _parse_bool_setting(model_settings.get("ollama_no_think"), default=default)


def normalize_model_runtime(
    model_settings: dict,
    *,
    default_provider: str = "ollama",
    default_model: str = "",
    default_api_base: Optional[str] = None,
    default_temperature: float = 0.2,
    default_max_tokens: int = 1000,
    fallback_api_key: Optional[str] = None,
    ollama_num_ctx_default: int = OLLAMA_NUM_CTX_TRANSLATION_DEFAULT,
    ollama_no_think_default: bool = False,
) -> ModelRuntime:
    """Build runtime from raw model settings."""
    provider = normalize_provider(model_settings.get("provider"), default_provider=default_provider)
    model = str(model_settings.get("model") or "").strip() or default_model
    # Prefer the provider's catalog default (e.g. MiniMax → api.minimaxi.com/v1)
    # over a stale Ollama localhost URL left behind after a provider switch.
    api_base = sanitize_provider_api_base(
        provider,
        model_settings.get("api_base"),
        fallback_default=default_api_base,
    )
    api_key = str(model_settings.get("api_key") or "").strip() or fallback_api_key
    temperature = _coerce_float(model_settings.get("temperature"), default_temperature, min_value=0.0, max_value=2.0)
    max_tokens = _coerce_int(model_settings.get("max_tokens"), default_max_tokens, min_value=1, max_value=16000)
    ollama_num_ctx = resolve_ollama_num_ctx(model_settings, default=ollama_num_ctx_default)
    ollama_no_think = resolve_ollama_no_think(model_settings, default=ollama_no_think_default)
    return ModelRuntime(
        provider=provider,
        model=model,
        api_base=api_base,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        ollama_num_ctx=ollama_num_ctx,
        ollama_no_think=ollama_no_think,
    )


def _normalize_api_base(api_base: Optional[str], default: str = "http://localhost:11434") -> str:
    value = str(api_base or "").strip().rstrip("/")
    return value or default


def append_ollama_no_think(content: str, *, enabled: bool = True) -> str:
    """Append /no_think to disable chain-of-thought when enabled."""
    text = str(content or "").strip()
    if not enabled or not text or "/no_think" in text:
        return content or ""
    return f"{text} /no_think"


def ollama_request_options(
    *,
    temperature: float,
    num_ctx: int = OLLAMA_NUM_CTX_TRANSLATION_DEFAULT,
    num_predict: Optional[int] = None,
) -> dict:
    opts = {
        "temperature": temperature,
        "num_ctx": num_ctx,
    }
    if num_predict is not None and num_predict > 0:
        opts["num_predict"] = num_predict
    return opts


def _ollama_stream_deltas(data: dict) -> tuple[str, str]:
    """Extract visible and thinking deltas from one Ollama NDJSON chunk."""
    message = data.get("message") or {}
    visible = str(message.get("content") or data.get("response") or "")
    thinking = str(message.get("thinking") or data.get("thinking") or "")
    return visible, thinking


async def _read_ollama_stream(
    resp: httpx.Response,
    *,
    use_thinking_fallback: bool = False,
) -> str:
    """Collect streamed text; optionally fall back to thinking when visible is empty."""
    visible_parts: list[str] = []
    thinking_parts: list[str] = []
    async for line in resp.aiter_lines():
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        visible, thinking = _ollama_stream_deltas(data)
        if visible:
            visible_parts.append(visible)
        if thinking:
            thinking_parts.append(thinking)
        if data.get("done"):
            break
    text = "".join(visible_parts).strip()
    if text or not use_thinking_fallback:
        return text
    return "".join(thinking_parts).strip()


async def _read_ollama_native_chat_stream(
    resp: httpx.Response,
    *,
    use_thinking_fallback: bool = False,
) -> str:
    return await _read_ollama_stream(resp, use_thinking_fallback=use_thinking_fallback)


async def _read_ollama_generate_stream(
    resp: httpx.Response,
    *,
    use_thinking_fallback: bool = False,
) -> str:
    return await _read_ollama_stream(resp, use_thinking_fallback=use_thinking_fallback)


async def _read_ollama_chat_stream(resp: httpx.Response) -> str:
    parts: list[str] = []
    async for line in resp.aiter_lines():
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue
        choices = data.get("choices") or [{}]
        delta = (choices[0].get("delta") or {}).get("content")
        if delta:
            parts.append(str(delta))
    return "".join(parts).strip()


async def ollama_generate_text(
    *,
    api_base: Optional[str],
    model: str,
    prompt: str,
    system_prompt: Optional[str] = None,
    temperature: float = 0.2,
    timeout_seconds: float = 180.0,
    no_think: bool = False,
    num_ctx: int = OLLAMA_NUM_CTX_TRANSLATION_DEFAULT,
    num_predict: Optional[int] = None,
) -> str:
    """Generate text via local Ollama with streaming and tuned runtime options."""
    base = _normalize_api_base(api_base)
    if system_prompt:
        merged_prompt = f"{append_ollama_no_think(system_prompt, enabled=no_think)}\n\n{prompt}"
    else:
        merged_prompt = append_ollama_no_think(prompt, enabled=no_think)

    sys_content = append_ollama_no_think(
        system_prompt or "You are a helpful assistant.",
        enabled=no_think,
    )
    options = ollama_request_options(
        temperature=temperature,
        num_ctx=num_ctx,
        num_predict=num_predict,
    )

    generate_payload: dict = {
        "model": model,
        "prompt": merged_prompt,
        "stream": True,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": options,
    }
    # Qwen3+ models emit chain-of-thought in ``thinking`` with empty ``content`` unless
    # the API flag is set; prompt-only /no_think is not reliable on its own.
    if no_think:
        generate_payload["think"] = False

    chat_payload: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": sys_content},
            {"role": "user", "content": prompt},
        ],
        "stream": True,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": options,
    }
    if no_think:
        chat_payload["think"] = False

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        attempts = (
            [("chat", f"{base}/api/chat", chat_payload, _read_ollama_native_chat_stream)]
            + [("generate", f"{base}/api/generate", generate_payload, _read_ollama_generate_stream)]
            if no_think
            else [
                ("generate", f"{base}/api/generate", generate_payload, _read_ollama_generate_stream),
                ("chat", f"{base}/api/chat", chat_payload, _read_ollama_native_chat_stream),
            ]
        )
        use_thinking_fallback = not no_think
        for label, url, payload, reader in attempts:
            try:
                async with client.stream("POST", url, json=payload) as resp:
                    if resp.status_code != 200:
                        continue
                    text = await reader(resp, use_thinking_fallback=use_thinking_fallback)
                    if text:
                        return text
            except Exception:
                logger.debug("Ollama %s stream failed", label, exc_info=True)
    return ""


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


async def _resolve_runtime_from_model_settings(
    model_settings: dict[str, Any],
    *,
    default_provider: str,
    default_model: str,
    default_api_base: Optional[str] = None,
    default_temperature: float = 0.2,
    default_max_tokens: int = 1000,
    ollama_num_ctx_default: int = OLLAMA_NUM_CTX_TRANSLATION_DEFAULT,
    ollama_no_think_default: bool = False,
) -> Optional[ModelRuntime]:
    settings = get_settings()
    enriched = enrich_model_settings_from_api_config(model_settings)
    runtime = normalize_model_runtime(
        enriched,
        default_provider=default_provider,
        default_model=default_model,
        default_api_base=default_api_base,
        default_temperature=default_temperature,
        default_max_tokens=default_max_tokens,
        fallback_api_key=getattr(settings, "openai_api_key", None),
        ollama_num_ctx_default=ollama_num_ctx_default,
        ollama_no_think_default=ollama_no_think_default,
    )

    if runtime.provider == "ollama":
        return await _resolve_ollama_runtime(runtime, default_model=default_model)

    if not runtime.model:
        return None

    if runtime.provider == "openai" and not runtime.api_key:
        return None

    if runtime.provider not in {"openai", "ollama"} and not runtime.api_key:
        return None
    if runtime.provider not in {"openai", "ollama"} and not runtime.api_base:
        logger.warning("AI provider %s requires a configured API base; runtime disabled", runtime.provider)
        return None

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
    runtime_settings = get_system_settings_sync() or {}
    model_settings = (runtime_settings.get(setting_key) or {}) if isinstance(runtime_settings, dict) else {}
    if not isinstance(model_settings, dict):
        model_settings = {}

    if setting_key == "ai_model":
        ollama_num_ctx_default = OLLAMA_NUM_CTX_WRITING_DEFAULT
        ollama_no_think_default = False
    elif setting_key == "translation_model":
        ollama_num_ctx_default = OLLAMA_NUM_CTX_TRANSLATION_DEFAULT
        ollama_no_think_default = True
    elif setting_key == "atom_model":
        ollama_num_ctx_default = OLLAMA_NUM_CTX_WRITING_DEFAULT
        ollama_no_think_default = False
    elif setting_key == "score_model":
        ollama_num_ctx_default = OLLAMA_NUM_CTX_TRANSLATION_DEFAULT
        ollama_no_think_default = True
    else:
        ollama_num_ctx_default = OLLAMA_NUM_CTX_TRANSLATION_DEFAULT
        ollama_no_think_default = False

    return await _resolve_runtime_from_model_settings(
        model_settings,
        default_provider=default_provider,
        default_model=default_model,
        default_api_base=default_api_base,
        default_temperature=default_temperature,
        default_max_tokens=default_max_tokens,
        ollama_num_ctx_default=ollama_num_ctx_default,
        ollama_no_think_default=ollama_no_think_default,
    )


async def get_atom_extraction_runtime() -> Optional[ModelRuntime]:
    """Resolve the LLM runtime for news atom extraction.

    When ``atom_model.model`` is empty, falls back to ``ai_model``.
    """
    runtime_settings = get_system_settings_sync() or {}
    atom_settings = runtime_settings.get("atom_model") if isinstance(runtime_settings.get("atom_model"), dict) else {}
    ai_settings = runtime_settings.get("ai_model") if isinstance(runtime_settings.get("ai_model"), dict) else {}
    if not isinstance(atom_settings, dict):
        atom_settings = {}
    if not isinstance(ai_settings, dict):
        ai_settings = {}

    dedicated_model = str(atom_settings.get("model") or "").strip()
    if dedicated_model:
        merged = {**ai_settings, **atom_settings}
    else:
        merged = dict(ai_settings)

    temperature = atom_settings.get("temperature", merged.get("temperature", 0.1))
    max_tokens = atom_settings.get("max_tokens", merged.get("max_tokens", 4000))

    return await _resolve_runtime_from_model_settings(
        merged,
        default_provider=str(merged.get("provider") or "ollama"),
        default_model=str(merged.get("model") or ""),
        default_api_base=merged.get("api_base") or "http://localhost:11434",
        default_temperature=float(temperature if temperature is not None else 0.1),
        default_max_tokens=int(max_tokens if max_tokens is not None else 4000),
        ollama_num_ctx_default=OLLAMA_NUM_CTX_WRITING_DEFAULT,
        ollama_no_think_default=False,
    )


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
        no_think: Optional[bool] = None,
        num_ctx: Optional[int] = None,
    ) -> str:
        from app.platform.llm.policy import ai_hard_disabled, ai_processing_paused

        if ai_hard_disabled():
            logger.info("AI processing hard-disabled; skipping LLM call")
            return ""
        if ai_processing_paused():
            logger.info("AI processing paused by system settings; skipping LLM call")
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
                no_think=runtime.ollama_no_think if no_think is None else no_think,
                num_ctx=runtime.ollama_num_ctx if num_ctx is None else num_ctx,
                num_predict=mt,
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
        no_think: bool = False,
        num_ctx: int = OLLAMA_NUM_CTX_TRANSLATION_DEFAULT,
        num_predict: Optional[int] = None,
    ) -> str:
        temp = runtime.temperature if temperature is None else temperature
        return await ollama_generate_text(
            api_base=runtime.api_base,
            model=runtime.model,
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temp,
            timeout_seconds=timeout_seconds,
            no_think=no_think,
            num_ctx=num_ctx,
            num_predict=num_predict,
        )

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
        client = openai.AsyncOpenAI(max_retries=0, **kwargs)
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
