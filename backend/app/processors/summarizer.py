"""Content summarization using OpenAI."""

from typing import Optional

from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


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
            from app.services.system_settings import get_system_settings_sync

            return get_system_settings_sync()
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

        runtime_settings = self._get_runtime_settings()
        ai_model = runtime_settings.get("ai_model", {}) or {}
        provider = ai_model.get("provider", "ollama")
        model = ai_model.get("model", "gpt-4.1-mini")
        api_base = ai_model.get("api_base", "http://localhost:11434")
        api_key = ai_model.get("api_key")
        cloud_fallback_enabled = bool(
            runtime_settings.get("summarization_cloud_fallback_enabled", False)
        )

        try:
            if provider == "ollama":
                summary = await self._summarize_with_ollama(
                    text=text,
                    max_length=max_length,
                    language=language,
                    model=model,
                    api_base=api_base,
                )
                if summary:
                    return summary
                if not cloud_fallback_enabled:
                    logger.info("Ollama summarization failed and cloud fallback is disabled")
                    return text[:max_length] + "..." if len(text) > max_length else text

            # Cloud path (OpenAI and OpenAI-compatible gateways)
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

            return text[:max_length] + "..." if len(text) > max_length else text

        except Exception as e:
            logger.error(f"Error generating summary: {e}")
            # Fall back to simple truncation
            return text[:max_length] + "..." if len(text) > max_length else text

    async def _summarize_with_ollama(
        self,
        text: str,
        max_length: int,
        language: str,
        model: str,
        api_base: str,
    ) -> Optional[str]:
        """Summarize with local Ollama."""
        try:
            import httpx

            max_input_length = 4000
            if len(text) > max_input_length:
                text = text[:max_input_length] + "..."

            lang_instruction = "中文" if language.startswith("zh") else language
            prompt = (
                f"请用{lang_instruction}总结下面内容，限制在{max_length}字以内。"
                "只输出摘要正文，不要解释。\n\n"
                f"{text}"
            )

            async with httpx.AsyncClient(timeout=90.0) as client:
                resp = await client.post(
                    f"{api_base}/api/generate",
                    json={
                        "model": model,
                        "prompt": prompt,
                        "stream": False,
                    },
                )
            if resp.status_code != 200:
                return None

            result = resp.json().get("response", "").strip()
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
    
    async def extract_keywords(self, text: str, max_keywords: int = 5) -> list:
        """Extract key topics/keywords from text."""
        if not text or len(text.strip()) < 50:
            return []
        
        try:
            runtime_settings = self._get_runtime_settings()
            ai_model = runtime_settings.get("ai_model", {}) or {}
            provider = ai_model.get("provider", "ollama")
            model = ai_model.get("model", "gpt-4o-mini")
            api_base = ai_model.get("api_base")
            api_key = ai_model.get("api_key")

            if provider == "ollama":
                keywords_str = await self._extract_keywords_with_ollama(
                    text=text,
                    max_keywords=max_keywords,
                    model=model or "deepseek-r1:14b",
                    api_base=api_base or "http://localhost:11434",
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
    ) -> Optional[str]:
        """Extract keywords with Ollama local model."""
        try:
            import httpx

            prompt = (
                f"请从下面内容提取不超过{max_keywords}个关键词。"
                "仅输出关键词，使用英文逗号分隔，不要解释。\n\n"
                f"{text[:3000]}"
            )

            async with httpx.AsyncClient(timeout=90.0) as client:
                resp = await client.post(
                    f"{api_base}/api/generate",
                    json={
                        "model": model,
                        "prompt": prompt,
                        "stream": False,
                    },
                )
            if resp.status_code != 200:
                return None
            return (resp.json().get("response") or "").strip() or None
        except Exception as e:
            logger.error(f"Ollama keyword extraction error: {e}")
            return None
