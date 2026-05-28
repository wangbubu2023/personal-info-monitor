"""Content translation."""

import re
from typing import Optional

from app.ai.provider import (
    ModelProviderClient,
    ModelRuntime,
    OLLAMA_NUM_CTX_TRANSLATION_DEFAULT,
    list_ollama_models,
    normalize_model_runtime,
)
from app.platform.config.settings import get_settings
from app.platform.observability.logger import get_logger
from app.utils.model_catalog import sanitize_provider_api_base

logger = get_logger(__name__)


def get_translation_settings():
    """Get translation model settings from system config."""
    try:
        from app.services.api_config_credentials import enrich_model_settings_from_api_config
        from app.platform.config.system_settings import get_system_settings_sync

        settings = get_system_settings_sync()
        model_settings = settings.get("translation_model", {})
        if not isinstance(model_settings, dict):
            return {}
        result = enrich_model_settings_from_api_config(model_settings)
        if result.get("provider") == "ollama" and not result.get("api_base"):
            result["api_base"] = "http://localhost:11434"
        return result
    except Exception as exc:
        logger.warning("Translation config parsing failed: %s", exc)
        return {}


def is_translation_cloud_fallback_enabled() -> bool:
    """Whether fallback translation is enabled (any configured provider)."""
    try:
        from app.platform.config.system_settings import get_system_settings_sync

        settings = get_system_settings_sync() or {}
        if "translation_fallback_enabled" in settings:
            return bool(settings.get("translation_fallback_enabled"))
        return bool(settings.get("translation_cloud_fallback_enabled", False))
    except Exception as exc:
        logger.debug("Translation fallback flag read failed: %s", exc)
        return False


def is_translation_fallback_enabled() -> bool:
    """Preferred name; delegates to :func:`is_translation_cloud_fallback_enabled` for patch compatibility."""
    return is_translation_cloud_fallback_enabled()


def get_translation_fallback_model_settings() -> dict:
    """Enriched provider/model dict for translation fallback from 模型接入."""
    try:
        from app.services.api_config_credentials import enrich_model_settings_from_api_config
        from app.platform.config.system_settings import get_system_settings_sync

        s = get_system_settings_sync() or {}
        if not is_translation_cloud_fallback_enabled():
            return {}
        fb = s.get("translation_fallback") or {}
        if not isinstance(fb, dict):
            return {}
        prov = str(fb.get("provider") or "").strip()
        mod = str(fb.get("model") or "").strip()
        if not prov or not mod:
            return {}
        return enrich_model_settings_from_api_config(dict(fb))
    except Exception as exc:
        logger.warning("Translation fallback model settings failed: %s", exc)
        return {}


def _translation_prompt_char_limit(num_ctx: int) -> int:
    """Reserve context for system prompt + instructions when num_ctx is small."""
    # ~4 chars/token; keep user payload under half of ctx after overhead.
    return max(200, min(1200, (num_ctx - 768) * 2))


def _translation_num_predict(text: str, *, max_tokens: int) -> int:
    """Cap generation length so small local models return quickly."""
    est = max(64, min(len(text) * 2, 512))
    return min(max_tokens, est)


def _provider_model_pair(cfg: dict) -> tuple[str, str]:
    if not isinstance(cfg, dict):
        return ("", "")
    return (
        str(cfg.get("provider") or "").strip().lower(),
        str(cfg.get("model") or "").strip(),
    )


def get_translation_cloud_fallback_openai_settings() -> dict:
    """Resolve OpenAI-compatible cloud fallback settings."""
    try:
        from app.services.api_config_credentials import enrich_model_settings_from_api_config
        from app.platform.config.system_settings import get_system_settings_sync

        settings = get_system_settings_sync()
        trans_model = enrich_model_settings_from_api_config(settings.get("translation_model", {}) or {})
        ai_model = enrich_model_settings_from_api_config(settings.get("ai_model", {}) or {})

        model = trans_model.get("fallback_model") or ai_model.get("model") or "gpt-4o-mini"
        api_base = trans_model.get("fallback_api_base")
        if api_base in (None, ""):
            api_base = ai_model.get("api_base")
        api_key = trans_model.get("fallback_api_key")
        if api_key in (None, ""):
            api_key = ai_model.get("api_key")

        return {
            "provider": "openai",
            "model": model,
            "api_base": api_base,
            "api_key": api_key,
            "temperature": 0.1,
            "max_tokens": 1200,
        }
    except Exception as exc:
        logger.warning("Translation config fallback failed: %s", exc)
        return {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "temperature": 0.1,
            "max_tokens": 1200,
        }


def _resolve_translation_fallback_settings(primary: dict) -> dict:
    """Explicit fallback from settings, or legacy merge from primary/ai model."""
    fb = get_translation_fallback_model_settings()
    if fb:
        return fb
    return get_translation_cloud_fallback_openai_settings()


class Translator:
    """Translate content between languages."""

    def __init__(self):
        self.settings = get_settings()
        self.model_client = ModelProviderClient()
        self._async_openai_client = None
        self._async_openai_key: Optional[str] = None
        self._async_openai_base: Optional[str] = None

    def is_chinese(self, text: str) -> bool:
        """Check if text is primarily Chinese."""
        if not text:
            return False

        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
        total_chars = len(re.findall(r"\w", text))
        if total_chars == 0:
            return False
        return chinese_chars / total_chars > 0.3

    def detect_language(self, text: str) -> str:
        """Simple language detection."""
        if not text:
            return "unknown"
        if self.is_chinese(text):
            return "zh"
        if re.search(r"[\u3040-\u309f\u30a0-\u30ff]", text):
            return "ja"
        if re.search(r"[\uac00-\ud7af]", text):
            return "ko"
        return "en"

    async def _resolve_runtime(self, model_settings: dict, *, default_model: str) -> Optional[ModelRuntime]:
        runtime = normalize_model_runtime(
            model_settings,
            default_provider=str(model_settings.get("provider") or "ollama"),
            default_model=default_model,
            default_api_base="http://localhost:11434",
            default_temperature=0.1,
            default_max_tokens=1200,
            fallback_api_key=self.settings.openai_api_key,
            ollama_num_ctx_default=OLLAMA_NUM_CTX_TRANSLATION_DEFAULT,
            ollama_no_think_default=True,
        )

        if runtime.provider == "ollama":
            names = await list_ollama_models(runtime.api_base)
            if not names:
                return None
            if runtime.model not in names:
                runtime.model = names[0]
            return runtime

        if not runtime.model:
            return None
        if runtime.provider in {"openai", "anthropic", "google", "qwen"} and not runtime.api_key:
            return None
        return runtime

    async def _translate_with_runtime(
        self,
        text: str,
        target_language: str,
        runtime: Optional[ModelRuntime],
    ) -> Optional[str]:
        if runtime is None:
            return None

        lang_name = {
            "zh-CN": "简体中文",
            "zh-TW": "繁体中文",
            "en": "English",
            "ja": "日本語",
            "ko": "한국어",
        }.get(target_language, target_language)

        char_limit = 3000
        num_predict = 1200
        if runtime.provider == "ollama":
            num_ctx = runtime.ollama_num_ctx or OLLAMA_NUM_CTX_TRANSLATION_DEFAULT
            char_limit = _translation_prompt_char_limit(num_ctx)
            num_predict = _translation_num_predict(text, max_tokens=runtime.max_tokens)

        prompt = (
            f"请将下面内容翻译为{lang_name}。"
            "只返回译文，不要解释，不要保留原文。\n\n"
            f"{text[:char_limit]}"
        )
        try:
            timeout = 180.0 if runtime.provider == "ollama" else 60.0
            translated = await self.model_client.generate_text(
                runtime,
                prompt=prompt,
                system_prompt="你是一个严谨的翻译助手。",
                temperature=0.1,
                max_tokens=num_predict,
                timeout_seconds=timeout,
                # Always disable Ollama chain-of-thought API; prompt /no_think follows settings.
                no_think=True if runtime.provider == "ollama" else None,
            )
            translated = (translated or "").strip()
            if translated:
                logger.info(
                    "Translated with %s (%s): %s -> %s chars",
                    runtime.provider,
                    runtime.model,
                    len(text),
                    len(translated),
                )
                return translated
            return None
        except Exception as e:
            logger.warning(f"Translation via {runtime.provider} failed: {e}")
            return None

    def _get_async_openai_client(self, api_key: Optional[str], api_base: Optional[str]):
        """Get or create async OpenAI-compatible client."""
        if not api_key:
            raise ValueError("OpenAI API key not configured")
        if (
            self._async_openai_client is not None
            and self._async_openai_key == api_key
            and self._async_openai_base == api_base
        ):
            return self._async_openai_client

        import openai

        kwargs = {"api_key": api_key}
        if api_base:
            kwargs["base_url"] = api_base
        self._async_openai_client = openai.AsyncOpenAI(max_retries=0, **kwargs)
        self._async_openai_key = api_key
        self._async_openai_base = api_base
        return self._async_openai_client

    async def _translate_with_ollama(
        self,
        text: str,
        target_language: str,
        trans_settings: dict,
    ) -> Optional[str]:
        runtime = await self._resolve_runtime(trans_settings, default_model="")
        if not runtime or runtime.provider != "ollama":
            return None
        return await self._translate_with_runtime(text, target_language, runtime)

    async def _translate_with_openai(
        self,
        text: str,
        target_language: str,
        trans_settings: Optional[dict] = None,
    ) -> Optional[str]:
        if not self.settings.ai_processing_enabled or not self.settings.enrich_translate_enabled:
            return None
        model_cfg = trans_settings if isinstance(trans_settings, dict) else {}
        model = str(model_cfg.get("model") or "").strip() or "gpt-4o-mini"
        provider = str(model_cfg.get("provider") or "openai").strip().lower()
        api_base = sanitize_provider_api_base(provider, model_cfg.get("api_base"))
        api_key = str(model_cfg.get("api_key") or "").strip() or self.settings.openai_api_key
        if not api_key:
            return None
        if provider != "openai" and not api_base:
            logger.warning("Translation provider %s has no API base; skipping", provider)
            return None

        lang_name = {
            "zh-CN": "简体中文",
            "zh-TW": "繁体中文",
            "en": "English",
            "ja": "日本語",
            "ko": "한국어",
        }.get(target_language, target_language)
        prompt = text[:3000]
        try:
            client = self._get_async_openai_client(api_key=api_key, api_base=api_base)
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": f"你是一个专业的翻译助手。请将用户的内容翻译成{lang_name}。只返回翻译结果，不要添加任何解释。",
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=1200,
                temperature=0.1,
            )
            translated = (response.choices[0].message.content or "").strip()
            return translated or None
        except Exception as e:
            logger.warning(f"OpenAI-compatible translation failed: {e}")
            return None

    async def _translate_with_provider_settings(
        self,
        text: str,
        target_language: str,
        cfg: dict,
    ) -> Optional[str]:
        provider = str(cfg.get("provider") or "ollama").strip().lower()
        if provider == "ollama":
            return await self._translate_with_ollama(text, target_language, cfg)
        return await self._translate_with_openai(text, target_language, cfg)

    async def translate(
        self,
        text: str,
        target_language: str = "zh-CN",
        source_language: Optional[str] = None,
    ) -> Optional[str]:
        """Translate text to target language."""
        if not text or len(text.strip()) < 5:
            return None
        if not self.settings.ai_processing_enabled or not self.settings.enrich_translate_enabled:
            return None

        if source_language is None:
            source_language = self.detect_language(text)
        if source_language.startswith(target_language[:2]):
            return None

        trans_settings = get_translation_settings()
        provider = str(trans_settings.get("provider") or "ollama").strip().lower()
        fallback_enabled = is_translation_cloud_fallback_enabled()

        async def try_fallback() -> Optional[str]:
            if not fallback_enabled:
                return None
            fallback_settings = _resolve_translation_fallback_settings(trans_settings)
            if not fallback_settings:
                return None
            if _provider_model_pair(trans_settings) == _provider_model_pair(fallback_settings):
                logger.info("Translation fallback skipped: same provider/model as primary")
                return None
            return await self._translate_with_provider_settings(text, target_language, fallback_settings)

        if provider == "ollama":
            translated = await self._translate_with_ollama(text, target_language, trans_settings)
            if translated:
                return translated

            if not fallback_enabled:
                logger.info("Ollama translation failed and translation fallback is disabled")
                return None

            logger.info("Ollama translation failed; trying fallback model")
            return await try_fallback()

        translated = await self._translate_with_openai(text, target_language, trans_settings)
        if translated:
            return translated
        return await try_fallback()

    async def translate_with_fallback(
        self,
        text: str,
        target_language: str = "zh-CN",
    ) -> Optional[str]:
        """Last-resort translation when primary output is unusable.

        Uses the same fallback model as :meth:`translate` (when enabled).
        """
        if not text or len(text.strip()) < 5:
            return None
        if not is_translation_cloud_fallback_enabled():
            return None
        trans_settings = get_translation_settings()
        fallback_settings = _resolve_translation_fallback_settings(trans_settings)
        if not fallback_settings:
            return None
        if _provider_model_pair(trans_settings) == _provider_model_pair(fallback_settings):
            return None
        return await self._translate_with_provider_settings(text, target_language, fallback_settings)
