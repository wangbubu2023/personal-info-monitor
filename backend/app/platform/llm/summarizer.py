"""Content summarization using OpenAI."""

from typing import Any, Optional

from app.platform.config.settings import get_settings
from app.platform.observability.logger import get_logger

logger = get_logger(__name__)


def _is_summarization_fallback_enabled(runtime: dict) -> bool:
    if not isinstance(runtime, dict):
        return False
    if "summarization_fallback_enabled" in runtime:
        return bool(runtime.get("summarization_fallback_enabled"))
    return bool(runtime.get("summarization_cloud_fallback_enabled", False))


def get_summarization_fallback_model_settings(runtime: Optional[dict[str, Any]] = None) -> dict:
    """Enriched provider/model dict for summarization fallback from 模型接入.

    Pass ``runtime`` (e.g. from :meth:`Summarizer._get_runtime_settings`) so tests
    and callers see the same flags as the summarize path without relying on sync cache.
    """
    try:
        from app.services.api_config_credentials import enrich_model_settings_from_api_config
        from app.platform.config.system_settings import get_system_settings_sync

        s = (runtime if runtime is not None else (get_system_settings_sync() or {})) or {}
        if not _is_summarization_fallback_enabled(s):
            return {}
        fb = s.get("summarization_fallback") or {}
        if not isinstance(fb, dict):
            return {}
        prov = str(fb.get("provider") or "").strip()
        mod = str(fb.get("model") or "").strip()
        if not prov or not mod:
            return {}
        return enrich_model_settings_from_api_config(dict(fb))
    except Exception as exc:
        logger.warning("Summarization fallback model settings failed: %s", exc)
        return {}


def _provider_model_pair(cfg: dict) -> tuple[str, str]:
    if not isinstance(cfg, dict):
        return ("", "")
    return (
        str(cfg.get("provider") or "").strip().lower(),
        str(cfg.get("model") or "").strip(),
    )


class Summarizer:
    """Generate summaries using OpenAI GPT."""
    
    def __init__(self, api_key: Optional[str] = None):
        settings = get_settings()
        self.api_key = api_key or settings.openai_api_key
        self.client = None
        self._client_key: tuple[Optional[str], Optional[str]] | None = None
        self.async_client = None
        self._async_client_key: tuple[Optional[str], Optional[str]] | None = None

    def _get_runtime_settings(self) -> dict:
        """Read runtime AI settings from system config."""
        try:
            from app.platform.config.system_settings import get_system_settings_sync

            return get_system_settings_sync()
        except Exception:
            return {}

    def _get_ai_model_config(self) -> dict:
        """ai_model with api_configs (模型接入) merged in."""
        try:
            from app.services.api_config_credentials import enrich_model_settings_from_api_config

            raw = self._get_runtime_settings().get("ai_model") or {}
            if not isinstance(raw, dict):
                raw = {}
            return enrich_model_settings_from_api_config(raw)
        except Exception:
            return {}
    
    def _get_client(self, api_key: Optional[str] = None, api_base: Optional[str] = None):
        """Get or create OpenAI client."""
        resolved_api_key = api_key or self.api_key
        if not resolved_api_key:
            raise ValueError("OpenAI API key not configured")

        key = (resolved_api_key, api_base)
        if self.client is not None and self._client_key == key:
            return self.client
        
        import openai
        kwargs = {"api_key": resolved_api_key}
        if api_base:
            kwargs["base_url"] = api_base
        self.client = openai.OpenAI(**kwargs)
        self._client_key = key
        return self.client

    def _get_async_client(self, api_key: Optional[str] = None, api_base: Optional[str] = None):
        """Get or create async OpenAI client for coroutine paths."""
        resolved_api_key = api_key or self.api_key
        if not resolved_api_key:
            raise ValueError("OpenAI API key not configured")

        key = (resolved_api_key, api_base)
        if self.async_client is not None and self._async_client_key == key:
            return self.async_client

        import openai

        kwargs = {"api_key": resolved_api_key}
        if api_base:
            kwargs["base_url"] = api_base
        self.async_client = openai.AsyncOpenAI(**kwargs)
        self._async_client_key = key
        return self.async_client
    
    async def summarize(
        self,
        text: str,
        max_length: int = 300,
        language: str = "zh-CN"
    ) -> str:
        """
        Generate a summary of the given text.
        
        Args:
            text: The text to summarize
            max_length: Maximum length of the summary in characters
            language: Target language for the summary
        
        Returns:
            Summarized text
        """
        if not text or len(text.strip()) < 50:
            return text

        _settings = get_settings()
        if not _settings.ai_processing_enabled or not _settings.enrich_summary_enabled:
            return text[:max_length] + "..." if len(text) > max_length else text

        runtime_settings = self._get_runtime_settings()
        ai_model = self._get_ai_model_config()
        provider = ai_model.get("provider", "ollama")
        model = ai_model.get("model", "gpt-4.1-mini")
        api_base = ai_model.get("api_base", "http://localhost:11434")
        api_key = ai_model.get("api_key")
        fallback_enabled = _is_summarization_fallback_enabled(runtime_settings)

        def _truncate() -> str:
            return text[:max_length] + "..." if len(text) > max_length else text

        async def try_fallback() -> Optional[str]:
            if not fallback_enabled:
                return None
            fb = get_summarization_fallback_model_settings(runtime_settings)
            if not fb:
                api_key = str(self.api_key or "").strip()
                if not api_key:
                    return None
                fb = {
                    "provider": "openai",
                    "model": "gpt-4o-mini",
                    "api_key": api_key,
                    "api_base": None,
                }
            primary_pair = _provider_model_pair(ai_model)
            fb_pair = _provider_model_pair(fb)
            if primary_pair == fb_pair and primary_pair[0] and primary_pair[1]:
                logger.info("Summarization fallback skipped: same provider/model as primary")
                return None
            logger.info("Trying summarization fallback model")
            return await self._summarize_from_enriched_config(text, max_length, language, fb)

        try:
            if provider == "ollama":
                summary = await self._summarize_with_ollama(
                    text=text,
                    max_length=max_length,
                    language=language,
                    model=model,
                    api_base=api_base,
                    model_settings=ai_model,
                )
                if summary:
                    return summary

                if not fallback_enabled:
                    logger.info("Ollama summarization failed and summarization fallback is disabled; using truncation")
                    return _truncate()

                logger.info("Ollama summarization failed; trying fallback model")
                summary = await try_fallback()
                return summary or _truncate()

            summary = await self._summarize_with_openai(
                text=text,
                max_length=max_length,
                language=language,
                model=model,
                api_key=api_key,
                api_base=api_base if provider != "openai" else None,
            )
            if summary:
                return summary

            summary = await try_fallback()
            return summary or _truncate()

        except Exception as e:
            logger.error(f"Error generating summary: {e}")
            return _truncate()

    async def _summarize_with_ollama(
        self,
        text: str,
        max_length: int,
        language: str,
        model: str,
        api_base: str,
        model_settings: Optional[dict] = None,
    ) -> Optional[str]:
        """Summarize with local Ollama."""
        try:
            from app.ai.provider import (
                OLLAMA_NUM_CTX_WRITING_DEFAULT,
                ollama_generate_text,
                resolve_ollama_no_think,
                resolve_ollama_num_ctx,
            )

            cfg = model_settings if isinstance(model_settings, dict) else {}
            num_ctx = resolve_ollama_num_ctx(cfg, default=OLLAMA_NUM_CTX_WRITING_DEFAULT)
            no_think = resolve_ollama_no_think(cfg, default=False)

            max_input_length = 4000
            if len(text) > max_input_length:
                text = text[:max_input_length] + "..."

            lang_instruction = "中文" if language.startswith("zh") else language
            prompt = (
                f"请用{lang_instruction}总结下面内容，限制在{max_length}字以内。"
                "只输出摘要正文，不要解释。\n\n"
                f"{text}"
            )

            result = await ollama_generate_text(
                api_base=api_base,
                model=model,
                prompt=prompt,
                system_prompt="你是一个专业的内容写作助手。",
                temperature=0.3,
                timeout_seconds=90.0,
                no_think=no_think,
                num_ctx=num_ctx,
            )
            if result:
                logger.info(f"Generated summary with Ollama ({model}): {len(result)} characters")
                return result
            return None
        except Exception as e:
            logger.error(f"Ollama summarization error: {e}")
            return None

    async def _summarize_with_openai(
        self,
        text: str,
        max_length: int,
        language: str,
        model: str,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
    ) -> Optional[str]:
        """Summarize with OpenAI."""
        try:
            client = self._get_async_client(api_key=api_key, api_base=api_base)

            max_input_length = 4000
            if len(text) > max_input_length:
                text = text[:max_input_length] + "..."

            lang_instruction = "用中文" if language.startswith("zh") else f"用{language}"

            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": f"你是一个专业的内容摘要助手。请{lang_instruction}简洁地总结文章要点，突出关键信息。"
                    },
                    {
                        "role": "user",
                        "content": f"请将以下内容总结为{max_length}字以内的摘要:\n\n{text}"
                    }
                ],
                max_tokens=500,
                temperature=0.3
            )

            summary = response.choices[0].message.content.strip()
            logger.info(f"Generated summary with OpenAI-compatible provider ({model}): {len(summary)} characters")
            return summary
        except Exception as e:
            logger.error(f"OpenAI summarization error: {e}")
            return None

    async def _summarize_from_enriched_config(
        self,
        text: str,
        max_length: int,
        language: str,
        cfg: dict,
    ) -> Optional[str]:
        provider = str(cfg.get("provider") or "ollama").strip().lower()
        model = str(cfg.get("model") or "").strip() or "gpt-4o-mini"
        api_base = str(cfg.get("api_base") or "").strip() or "http://localhost:11434"
        api_key = cfg.get("api_key")
        if provider == "ollama":
            return await self._summarize_with_ollama(
                text=text,
                max_length=max_length,
                language=language,
                model=model,
                api_base=api_base,
                model_settings=cfg,
            )
        return await self._summarize_with_openai(
            text=text,
            max_length=max_length,
            language=language,
            model=model,
            api_key=api_key,
            api_base=api_base if provider != "openai" else None,
        )

    async def extract_keywords(self, text: str, max_keywords: int = 5) -> list:
        """Extract key topics/keywords from text."""
        if not text or len(text.strip()) < 50:
            return []
        
        try:
            runtime_settings = self._get_runtime_settings()
            ai_model = self._get_ai_model_config()
            provider = ai_model.get("provider", "ollama")
            model = ai_model.get("model", "gpt-4o-mini")
            api_base = ai_model.get("api_base")
            api_key = ai_model.get("api_key")

            if provider == "ollama":
                from app.ai.provider import list_ollama_models

                api_base = api_base or "http://localhost:11434"
                names = await list_ollama_models(api_base)
                if not names:
                    return []
                preferred = (model or "").strip()
                resolved_model = preferred if preferred in names else names[0]
                keywords_str = await self._extract_keywords_with_ollama(
                    text=text,
                    max_keywords=max_keywords,
                    model=resolved_model,
                    api_base=api_base,
                    model_settings=ai_model,
                )
                if not keywords_str:
                    return []
            else:
                client = self._get_async_client(
                    api_key=api_key or self.api_key,
                    api_base=api_base,
                )
                response = await client.chat.completions.create(
                    model=model or "gpt-4o-mini",
                    messages=[
                        {
                            "role": "system",
                            "content": "你是一个关键词提取助手。请从文本中提取最重要的关键词或主题。只返回关键词，用逗号分隔。"
                        },
                        {
                            "role": "user",
                            "content": f"请从以下内容中提取最多{max_keywords}个关键词:\n\n{text[:2000]}"
                        }
                    ],
                    max_tokens=100,
                    temperature=0.1
                )
                keywords_str = response.choices[0].message.content.strip()

            keywords = [k.strip() for k in keywords_str.split(",")]
            return keywords[:max_keywords]
            
        except Exception as e:
            logger.error(f"Error extracting keywords: {e}")
            return []

    async def _extract_keywords_with_ollama(
        self,
        text: str,
        max_keywords: int,
        model: str,
        api_base: str,
        model_settings: Optional[dict] = None,
    ) -> Optional[str]:
        """Extract keywords with Ollama local model."""
        try:
            from app.ai.provider import (
                OLLAMA_NUM_CTX_WRITING_DEFAULT,
                ollama_generate_text,
                resolve_ollama_no_think,
                resolve_ollama_num_ctx,
            )

            cfg = model_settings if isinstance(model_settings, dict) else {}
            num_ctx = resolve_ollama_num_ctx(cfg, default=OLLAMA_NUM_CTX_WRITING_DEFAULT)
            no_think = resolve_ollama_no_think(cfg, default=False)

            prompt = (
                f"请从下面内容提取不超过{max_keywords}个关键词。"
                "仅输出关键词，使用英文逗号分隔，不要解释。\n\n"
                f"{text[:3000]}"
            )

            result = await ollama_generate_text(
                api_base=api_base,
                model=model,
                prompt=prompt,
                system_prompt="你是一个关键词提取助手。",
                temperature=0.1,
                timeout_seconds=90.0,
                no_think=no_think,
                num_ctx=num_ctx,
            )
            return result or None
        except Exception as e:
            logger.error(f"Ollama keyword extraction error: {e}")
            return None
