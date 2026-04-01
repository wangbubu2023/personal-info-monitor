"""Content translation."""

import re
from typing import Optional

from app.ai.provider import (
    ModelProviderClient,
    ModelRuntime,
    list_ollama_models,
    normalize_model_runtime,
)
from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


def get_translation_settings():
    """Get translation model settings from system config."""
    try:
        from app.services.system_settings import get_system_settings_sync

        settings = get_system_settings_sync()
        model_settings = settings.get("translation_model", {})
        return model_settings if isinstance(model_settings, dict) else {}
    except Exception as exc:
        logger.warning("Translation config parsing failed: %s", exc)
        return {}


def is_translation_cloud_fallback_enabled() -> bool:
    """Whether cloud fallback (OpenAI/Google) is enabled for translation."""
    try:
        from app.services.system_settings import get_system_settings_sync

        settings = get_system_settings_sync()
        return bool(settings.get("translation_cloud_fallback_enabled", False))
    except Exception as exc:
        logger.debug("Translation availability check failed: %s", exc)
        return False


def get_translation_cloud_fallback_openai_settings() -> dict:
    """Resolve OpenAI-compatible cloud fallback settings."""
    try:
        from app.services.system_settings import get_system_settings_sync

        settings = get_system_settings_sync()
        trans_model = settings.get("translation_model", {}) or {}
        ai_model = settings.get("ai_model", {}) or {}

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

        prompt = (
            f"请将下面内容翻译为{lang_name}。"
            "只返回译文，不要解释，不要保留原文。\n\n"
            f"{text[:3000]}"
        )
        try:
            translated = await self.model_client.generate_text(
                runtime,
                prompt=prompt,
                system_prompt="你是一个严谨的翻译助手。",
                temperature=0.1,
                max_tokens=1200,
                timeout_seconds=60.0,
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
        self._async_openai_client = openai.AsyncOpenAI(**kwargs)
        self._async_openai_key = api_key
        self._async_openai_base = api_base
        return self._async_openai_client

    async def _translate_with_ollama(
        self,
        text: str,
        target_language: str,
        trans_settings: dict,
    ) -> Optional[str]:
        runtime = await self._resolve_runtime(trans_settings, default_model="translategemma:12b")
        if not runtime or runtime.provider != "ollama":
            return None
        return await self._translate_with_runtime(text, target_language, runtime)

    async def _translate_with_openai(
        self,
        text: str,
        target_language: str,
        trans_settings: Optional[dict] = None,
    ) -> Optional[str]:
        model_cfg = trans_settings if isinstance(trans_settings, dict) else {}
        model = str(model_cfg.get("model") or "").strip() or "gpt-4o-mini"
        api_base = str(model_cfg.get("api_base") or "").strip() or None
        api_key = str(model_cfg.get("api_key") or "").strip() or self.settings.openai_api_key
        if not api_key:
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

    async def translate(
        self,
        text: str,
        target_language: str = "zh-CN",
        source_language: Optional[str] = None,
    ) -> Optional[str]:
        """Translate text to target language."""
        if not text or len(text.strip()) < 5:
            return None

        if source_language is None:
            source_language = self.detect_language(text)
        if source_language.startswith(target_language[:2]):
            return None

        trans_settings = get_translation_settings()
        provider = str(trans_settings.get("provider") or "ollama").strip().lower()
        cloud_fallback_enabled = is_translation_cloud_fallback_enabled()

        if provider == "ollama":
            translated = await self._translate_with_ollama(text, target_language, trans_settings)
            if translated:
                return translated
            if not cloud_fallback_enabled:
                return None

            fallback_settings = get_translation_cloud_fallback_openai_settings()
            return await self._translate_with_openai(text, target_language, fallback_settings)

        translated = await self._translate_with_openai(text, target_language, trans_settings)
        if translated:
            return translated
        if not cloud_fallback_enabled:
            return None
        fallback_settings = get_translation_cloud_fallback_openai_settings()
        return await self._translate_with_openai(text, target_language, fallback_settings)

    async def translate_with_fallback(
        self,
        text: str,
        target_language: str = "zh-CN",
    ) -> Optional[str]:
        """Public fallback translation using cloud OpenAI-compatible provider.

        Intended as a last-resort attempt when ``translate()`` returns an
        invalid result.  Always uses the cloud fallback OpenAI settings
        regardless of the user's ``cloud_fallback_enabled`` flag.
        """
        if not text or len(text.strip()) < 5:
            return None
        fallback_settings = get_translation_cloud_fallback_openai_settings()
        return await self._translate_with_openai(text, target_language, fallback_settings)
