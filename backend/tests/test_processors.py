"""Tests for content extraction, summarization, and translation processors."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# ContentExtractor
# ---------------------------------------------------------------------------

class TestContentExtractor:

    @pytest.mark.asyncio
    async def test_extract_empty_html_returns_empty(self):
        from app.processors.extractor import ContentExtractor

        extractor = ContentExtractor()
        assert await extractor.extract("") == ""
        assert await extractor.extract(None) == ""

    @pytest.mark.asyncio
    async def test_extract_uses_trafilatura_first(self):
        from app.processors.extractor import ContentExtractor

        extractor = ContentExtractor()
        long_text = "A" * 200
        with patch("trafilatura.extract", return_value=long_text):
            result = await extractor.extract("<html><body>hello</body></html>")
        assert result == long_text

    @pytest.mark.asyncio
    async def test_extract_falls_back_to_beautifulsoup(self):
        from app.processors.extractor import ContentExtractor

        extractor = ContentExtractor()
        html = "<html><body><article>" + ("word " * 50) + "</article></body></html>"
        with patch("trafilatura.extract", return_value=None):
            result = await extractor.extract(html)
        assert "word" in result

    @pytest.mark.asyncio
    async def test_extract_trafilatura_short_falls_back(self):
        from app.processors.extractor import ContentExtractor

        extractor = ContentExtractor()
        html = "<html><body><article>" + ("content " * 30) + "</article></body></html>"
        with patch("trafilatura.extract", return_value="short"):
            result = await extractor.extract(html)
        assert len(result) > 5

    @pytest.mark.asyncio
    async def test_extract_trafilatura_exception(self):
        from app.processors.extractor import ContentExtractor

        extractor = ContentExtractor()
        html = "<html><body><article>" + ("text " * 30) + "</article></body></html>"
        with patch("trafilatura.extract", side_effect=RuntimeError("fail")):
            result = await extractor.extract(html)
        assert "text" in result

    @pytest.mark.asyncio
    async def test_extract_beautifulsoup_no_body(self):
        from app.processors.extractor import ContentExtractor

        extractor = ContentExtractor()
        with patch("trafilatura.extract", return_value=None):
            result = await extractor.extract("<html></html>")
        assert result == "" or isinstance(result, str)

    def test_extract_metadata_title(self):
        from app.processors.extractor import ContentExtractor

        extractor = ContentExtractor()
        html = '<html><head><title>Test Title</title></head><body></body></html>'
        meta = extractor.extract_metadata(html)
        assert meta.get("title") == "Test Title"

    def test_extract_metadata_description(self):
        from app.processors.extractor import ContentExtractor

        extractor = ContentExtractor()
        html = (
            '<html><head>'
            '<meta name="description" content="A test description">'
            '</head><body></body></html>'
        )
        meta = extractor.extract_metadata(html)
        assert meta["description"] == "A test description"

    def test_extract_metadata_og_image(self):
        from app.processors.extractor import ContentExtractor

        extractor = ContentExtractor()
        html = (
            '<html><head>'
            '<meta property="og:image" content="https://example.com/img.png">'
            '</head><body></body></html>'
        )
        meta = extractor.extract_metadata(html)
        assert meta["image"] == "https://example.com/img.png"

    def test_extract_metadata_keywords(self):
        from app.processors.extractor import ContentExtractor

        extractor = ContentExtractor()
        html = (
            '<html><head>'
            '<meta name="keywords" content="python, testing, ci">'
            '</head><body></body></html>'
        )
        meta = extractor.extract_metadata(html)
        assert meta["keywords"] == ["python", "testing", "ci"]

    def test_extract_metadata_published_time(self):
        from app.processors.extractor import ContentExtractor

        extractor = ContentExtractor()
        html = (
            '<html><head>'
            '<meta property="article:published_time" content="2025-01-15T10:00:00Z">'
            '</head><body></body></html>'
        )
        meta = extractor.extract_metadata(html)
        assert meta["published_time"] == "2025-01-15T10:00:00Z"

    def test_extract_metadata_author(self):
        from app.processors.extractor import ContentExtractor

        extractor = ContentExtractor()
        html = '<html><head><meta name="author" content="John"></head><body></body></html>'
        meta = extractor.extract_metadata(html)
        assert meta["author"] == "John"

    def test_extract_metadata_exception_returns_empty(self):
        from app.processors.extractor import ContentExtractor

        extractor = ContentExtractor()
        with patch("bs4.BeautifulSoup", side_effect=Exception("parse error")):
            meta = extractor.extract_metadata("<bad>")
        assert meta == {}


class TestExtractorHelpers:

    def test_remove_noise_elements(self):
        from bs4 import BeautifulSoup
        from app.processors.extractor import _remove_noise_elements

        html = '<html><body><nav>nav</nav><script>x</script><p>keep</p></body></html>'
        soup = BeautifulSoup(html, "lxml")
        _remove_noise_elements(soup)
        assert soup.find("nav") is None
        assert soup.find("script") is None
        assert soup.find("p") is not None

    def test_remove_noise_by_class(self):
        from bs4 import BeautifulSoup
        from app.processors.extractor import _remove_noise_elements

        html = '<html><body><div class="sidebar-left">ads</div><p>keep</p></body></html>'
        soup = BeautifulSoup(html, "lxml")
        _remove_noise_elements(soup)
        assert soup.find(class_="sidebar-left") is None
        assert soup.find("p") is not None

    def test_find_main_content_article(self):
        from bs4 import BeautifulSoup
        from app.processors.extractor import _find_main_content

        html = '<html><body><article>main</article><div>other</div></body></html>'
        soup = BeautifulSoup(html, "lxml")
        result = _find_main_content(soup)
        assert result.name == "article"

    def test_find_main_content_main_tag(self):
        from bs4 import BeautifulSoup
        from app.processors.extractor import _find_main_content

        html = '<html><body><main>main content</main></body></html>'
        soup = BeautifulSoup(html, "lxml")
        result = _find_main_content(soup)
        assert result.name == "main"

    def test_find_main_content_by_class(self):
        from bs4 import BeautifulSoup
        from app.processors.extractor import _find_main_content

        html = '<html><body><div class="content-area">text</div></body></html>'
        soup = BeautifulSoup(html, "lxml")
        result = _find_main_content(soup)
        assert "content" in (result.get("class", [""])[0]).lower()

    def test_find_main_content_by_id(self):
        from bs4 import BeautifulSoup
        from app.processors.extractor import _find_main_content

        html = '<html><body><div id="main-content">text</div></body></html>'
        soup = BeautifulSoup(html, "lxml")
        result = _find_main_content(soup)
        assert result is not None

    def test_find_main_content_falls_back_to_body(self):
        from bs4 import BeautifulSoup
        from app.processors.extractor import _find_main_content

        html = '<html><body><div>plain</div></body></html>'
        soup = BeautifulSoup(html, "lxml")
        result = _find_main_content(soup)
        assert result.name == "body"

    def test_extract_metadata_from_meta_tags_empty(self):
        from bs4 import BeautifulSoup
        from app.processors.extractor import _extract_metadata_from_meta_tags

        soup = BeautifulSoup("<html><head></head></html>", "lxml")
        assert _extract_metadata_from_meta_tags(soup) == {}


# ---------------------------------------------------------------------------
# Summarizer
# ---------------------------------------------------------------------------

class TestSummarizer:

    def _make_summarizer(self):
        with patch("app.processors.summarizer.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(openai_api_key="test-key")
            from app.processors.summarizer import Summarizer
            return Summarizer(api_key="test-key")

    @pytest.mark.asyncio
    async def test_summarize_short_text_returns_as_is(self):
        summarizer = self._make_summarizer()
        with patch.object(summarizer, "_get_runtime_settings", return_value={}):
            result = await summarizer.summarize("short")
        assert result == "short"

    @pytest.mark.asyncio
    async def test_summarize_empty_text(self):
        summarizer = self._make_summarizer()
        with patch.object(summarizer, "_get_runtime_settings", return_value={}):
            result = await summarizer.summarize("")
        assert result == ""

    @pytest.mark.asyncio
    async def test_summarize_ollama_success(self):
        summarizer = self._make_summarizer()
        long_text = "A" * 200
        settings = {"ai_model": {"provider": "ollama", "model": "llama", "api_base": "http://localhost:11434"}}
        with patch.object(summarizer, "_get_runtime_settings", return_value=settings), \
             patch.object(summarizer, "_summarize_with_ollama", new_callable=AsyncMock, return_value="summary"):
            result = await summarizer.summarize(long_text)
        assert result == "summary"

    @pytest.mark.asyncio
    async def test_summarize_ollama_fail_no_cloud_fallback(self):
        summarizer = self._make_summarizer()
        long_text = "A" * 200
        settings = {
            "ai_model": {"provider": "ollama", "model": "llama", "api_base": "http://localhost:11434"},
            "summarization_cloud_fallback_enabled": False,
        }
        with patch.object(summarizer, "_get_runtime_settings", return_value=settings), \
             patch.object(summarizer, "_summarize_with_ollama", new_callable=AsyncMock, return_value=None):
            result = await summarizer.summarize(long_text, max_length=50)
        assert result.endswith("...")

    @pytest.mark.asyncio
    async def test_summarize_ollama_fail_with_cloud_fallback(self):
        summarizer = self._make_summarizer()
        long_text = "A" * 200
        settings = {
            "ai_model": {"provider": "ollama", "model": "llama", "api_base": "http://localhost:11434"},
            "summarization_cloud_fallback_enabled": True,
        }
        with patch.object(summarizer, "_get_runtime_settings", return_value=settings), \
             patch.object(summarizer, "_summarize_with_ollama", new_callable=AsyncMock, return_value=None), \
             patch.object(summarizer, "_summarize_with_openai", new_callable=AsyncMock, return_value="cloud summary"):
            result = await summarizer.summarize(long_text)
        assert result == "cloud summary"

    @pytest.mark.asyncio
    async def test_summarize_openai_provider(self):
        summarizer = self._make_summarizer()
        long_text = "A" * 200
        settings = {"ai_model": {"provider": "openai", "model": "gpt-4o-mini", "api_key": "sk-test"}}
        with patch.object(summarizer, "_get_runtime_settings", return_value=settings), \
             patch.object(summarizer, "_summarize_with_openai", new_callable=AsyncMock, return_value="openai summary"):
            result = await summarizer.summarize(long_text)
        assert result == "openai summary"

    @pytest.mark.asyncio
    async def test_summarize_exception_truncates(self):
        summarizer = self._make_summarizer()
        long_text = "A" * 200
        settings = {"ai_model": {"provider": "openai", "model": "gpt-4o-mini", "api_key": "sk-test"}}
        with patch.object(summarizer, "_get_runtime_settings", return_value=settings), \
             patch.object(summarizer, "_summarize_with_openai", new_callable=AsyncMock, side_effect=Exception("api error")):
            result = await summarizer.summarize(long_text, max_length=50)
        assert result.endswith("...")
        assert len(result) <= 53

    @pytest.mark.asyncio
    async def test_summarize_with_ollama_http_success(self):
        summarizer = self._make_summarizer()
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {"response": "Ollama summary"}
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client
            result = await summarizer._summarize_with_ollama(
                text="Test text", max_length=300, language="zh-CN",
                model="llama", api_base="http://localhost:11434",
            )
        assert result == "Ollama summary"

    @pytest.mark.asyncio
    async def test_summarize_with_ollama_http_failure(self):
        summarizer = self._make_summarizer()
        mock_response = MagicMock(status_code=500)
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client
            result = await summarizer._summarize_with_ollama(
                text="Test text", max_length=300, language="en",
                model="llama", api_base="http://localhost:11434",
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_summarize_with_ollama_exception(self):
        summarizer = self._make_summarizer()
        with patch("httpx.AsyncClient", side_effect=Exception("conn error")):
            result = await summarizer._summarize_with_ollama(
                text="Test text", max_length=300, language="zh-CN",
                model="llama", api_base="http://localhost:11434",
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_summarize_with_ollama_truncates_long_input(self):
        summarizer = self._make_summarizer()
        long_text = "x" * 5000
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {"response": "shortened"}
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client
            result = await summarizer._summarize_with_ollama(
                text=long_text, max_length=300, language="zh-CN",
                model="llama", api_base="http://localhost:11434",
            )
        assert result == "shortened"

    @pytest.mark.asyncio
    async def test_summarize_with_openai_success(self):
        summarizer = self._make_summarizer()
        mock_msg = MagicMock()
        mock_msg.content = "AI summary"
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)
        with patch.object(summarizer, "_get_async_client", return_value=mock_client):
            result = await summarizer._summarize_with_openai(
                text="A" * 200, max_length=300, language="zh-CN",
                model="gpt-4o-mini", api_key="sk-test",
            )
        assert result == "AI summary"

    @pytest.mark.asyncio
    async def test_summarize_with_openai_exception(self):
        summarizer = self._make_summarizer()
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=Exception("api error"))
        with patch.object(summarizer, "_get_async_client", return_value=mock_client):
            result = await summarizer._summarize_with_openai(
                text="A" * 200, max_length=300, language="en",
                model="gpt-4o-mini", api_key="sk-test",
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_extract_keywords_short_text(self):
        summarizer = self._make_summarizer()
        result = await summarizer.extract_keywords("hi")
        assert result == []

    @pytest.mark.asyncio
    async def test_extract_keywords_empty(self):
        summarizer = self._make_summarizer()
        result = await summarizer.extract_keywords("")
        assert result == []

    @pytest.mark.asyncio
    async def test_extract_keywords_ollama(self):
        summarizer = self._make_summarizer()
        settings = {"ai_model": {"provider": "ollama", "model": "deepseek", "api_base": "http://localhost:11434"}}
        with patch.object(summarizer, "_get_runtime_settings", return_value=settings), \
             patch.object(summarizer, "_extract_keywords_with_ollama", new_callable=AsyncMock, return_value="AI, ML, NLP"):
            result = await summarizer.extract_keywords("A" * 100)
        assert result == ["AI", "ML", "NLP"]

    @pytest.mark.asyncio
    async def test_extract_keywords_ollama_returns_none(self):
        summarizer = self._make_summarizer()
        settings = {"ai_model": {"provider": "ollama", "model": "deepseek", "api_base": "http://localhost:11434"}}
        with patch.object(summarizer, "_get_runtime_settings", return_value=settings), \
             patch.object(summarizer, "_extract_keywords_with_ollama", new_callable=AsyncMock, return_value=None):
            result = await summarizer.extract_keywords("A" * 100)
        assert result == []

    @pytest.mark.asyncio
    async def test_extract_keywords_openai(self):
        summarizer = self._make_summarizer()
        settings = {"ai_model": {"provider": "openai", "model": "gpt-4o-mini", "api_key": "sk-test"}}
        mock_msg = MagicMock()
        mock_msg.content = "Python, Testing"
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)
        with patch.object(summarizer, "_get_runtime_settings", return_value=settings), \
             patch.object(summarizer, "_get_async_client", return_value=mock_client):
            result = await summarizer.extract_keywords("A" * 100)
        assert result == ["Python", "Testing"]

    @pytest.mark.asyncio
    async def test_extract_keywords_exception(self):
        summarizer = self._make_summarizer()
        with patch.object(summarizer, "_get_runtime_settings", side_effect=Exception("boom")):
            result = await summarizer.extract_keywords("A" * 100)
        assert result == []

    @pytest.mark.asyncio
    async def test_extract_keywords_with_ollama_http(self):
        summarizer = self._make_summarizer()
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {"response": "k1, k2"}
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client
            result = await summarizer._extract_keywords_with_ollama(
                text="A" * 200, max_keywords=5,
                model="deepseek", api_base="http://localhost:11434",
            )
        assert result == "k1, k2"

    @pytest.mark.asyncio
    async def test_extract_keywords_with_ollama_failure(self):
        summarizer = self._make_summarizer()
        mock_response = MagicMock(status_code=500)
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client
            result = await summarizer._extract_keywords_with_ollama(
                text="A" * 200, max_keywords=5,
                model="deepseek", api_base="http://localhost:11434",
            )
        assert result is None

    def test_get_client_caching(self):
        summarizer = self._make_summarizer()
        with patch("openai.OpenAI") as mock_openai:
            mock_openai.return_value = MagicMock()
            c1 = summarizer._get_client(api_key="k1")
            c2 = summarizer._get_client(api_key="k1")
            assert c1 is c2
            assert mock_openai.call_count == 1

    def test_get_client_different_key(self):
        summarizer = self._make_summarizer()
        with patch("openai.OpenAI") as mock_openai:
            mock_openai.return_value = MagicMock()
            summarizer._get_client(api_key="k1")
            summarizer._get_client(api_key="k2")
            assert mock_openai.call_count == 2

    def test_get_client_no_key_raises(self):
        with patch("app.processors.summarizer.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(openai_api_key=None)
            from app.processors.summarizer import Summarizer
            s = Summarizer(api_key=None)
        with pytest.raises(ValueError, match="API key"):
            s._get_client()

    def test_get_async_client_caching(self):
        summarizer = self._make_summarizer()
        with patch("openai.AsyncOpenAI") as mock_openai:
            mock_openai.return_value = MagicMock()
            c1 = summarizer._get_async_client(api_key="k1")
            c2 = summarizer._get_async_client(api_key="k1")
            assert c1 is c2
            assert mock_openai.call_count == 1

    def test_get_async_client_no_key_raises(self):
        with patch("app.processors.summarizer.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(openai_api_key=None)
            from app.processors.summarizer import Summarizer
            s = Summarizer(api_key=None)
        with pytest.raises(ValueError, match="API key"):
            s._get_async_client()

    def test_get_async_client_with_api_base(self):
        summarizer = self._make_summarizer()
        with patch("openai.AsyncOpenAI") as mock_openai:
            mock_openai.return_value = MagicMock()
            summarizer._get_async_client(api_key="k1", api_base="https://custom.api/v1")
            mock_openai.assert_called_once_with(api_key="k1", base_url="https://custom.api/v1")

    def test_get_runtime_settings_fallback(self):
        summarizer = self._make_summarizer()
        with patch("app.services.system_settings.get_system_settings_sync", side_effect=Exception("no db")):
            result = summarizer._get_runtime_settings()
        assert result == {}


# ---------------------------------------------------------------------------
# Translator
# ---------------------------------------------------------------------------

class TestTranslator:

    def _make_translator(self):
        with patch("app.processors.translator.get_settings") as mock_settings, \
             patch("app.processors.translator.ModelProviderClient") as mock_mpc:
            mock_settings.return_value = MagicMock(openai_api_key="sk-test")
            from app.processors.translator import Translator
            return Translator()

    def test_is_chinese_true(self):
        translator = self._make_translator()
        assert translator.is_chinese("这是中文测试") is True

    def test_is_chinese_false(self):
        translator = self._make_translator()
        assert translator.is_chinese("This is English") is False

    def test_is_chinese_empty(self):
        translator = self._make_translator()
        assert translator.is_chinese("") is False

    def test_is_chinese_only_symbols(self):
        translator = self._make_translator()
        assert translator.is_chinese("!!!###") is False

    def test_detect_language_chinese(self):
        translator = self._make_translator()
        assert translator.detect_language("这是中文测试内容") == "zh"

    def test_detect_language_english(self):
        translator = self._make_translator()
        assert translator.detect_language("This is English") == "en"

    def test_detect_language_japanese(self):
        translator = self._make_translator()
        assert translator.detect_language("これはテストです") == "ja"

    def test_detect_language_korean(self):
        translator = self._make_translator()
        assert translator.detect_language("한국어 테스트") == "ko"

    def test_detect_language_empty(self):
        translator = self._make_translator()
        assert translator.detect_language("") == "unknown"

    @pytest.mark.asyncio
    async def test_translate_short_text_returns_none(self):
        translator = self._make_translator()
        result = await translator.translate("hi")
        assert result is None

    @pytest.mark.asyncio
    async def test_translate_empty_returns_none(self):
        translator = self._make_translator()
        result = await translator.translate("")
        assert result is None

    @pytest.mark.asyncio
    async def test_translate_same_language_returns_none(self):
        translator = self._make_translator()
        result = await translator.translate("这是一段中文测试文本", target_language="zh-CN", source_language="zh")
        assert result is None

    @pytest.mark.asyncio
    async def test_translate_ollama_success(self):
        translator = self._make_translator()
        with patch("app.processors.translator.get_translation_settings", return_value={"provider": "ollama"}), \
             patch("app.processors.translator.is_translation_cloud_fallback_enabled", return_value=False), \
             patch.object(translator, "_translate_with_ollama", new_callable=AsyncMock, return_value="translated text"):
            result = await translator.translate("Hello world test text", target_language="zh-CN", source_language="en")
        assert result == "translated text"

    @pytest.mark.asyncio
    async def test_translate_ollama_fail_no_fallback(self):
        translator = self._make_translator()
        with patch("app.processors.translator.get_translation_settings", return_value={"provider": "ollama"}), \
             patch("app.processors.translator.is_translation_cloud_fallback_enabled", return_value=False), \
             patch.object(translator, "_translate_with_ollama", new_callable=AsyncMock, return_value=None):
            result = await translator.translate("Hello world test text", target_language="zh-CN", source_language="en")
        assert result is None

    @pytest.mark.asyncio
    async def test_translate_ollama_fail_with_cloud_fallback(self):
        translator = self._make_translator()
        with patch("app.processors.translator.get_translation_settings", return_value={"provider": "ollama"}), \
             patch("app.processors.translator.is_translation_cloud_fallback_enabled", return_value=True), \
             patch("app.processors.translator.get_translation_cloud_fallback_openai_settings", return_value={"model": "gpt-4o-mini", "api_key": "sk-test"}), \
             patch.object(translator, "_translate_with_ollama", new_callable=AsyncMock, return_value=None), \
             patch.object(translator, "_translate_with_openai", new_callable=AsyncMock, return_value="cloud translated"):
            result = await translator.translate("Hello world test text", target_language="zh-CN", source_language="en")
        assert result == "cloud translated"

    @pytest.mark.asyncio
    async def test_translate_openai_provider(self):
        translator = self._make_translator()
        with patch("app.processors.translator.get_translation_settings", return_value={"provider": "openai"}), \
             patch("app.processors.translator.is_translation_cloud_fallback_enabled", return_value=False), \
             patch.object(translator, "_translate_with_openai", new_callable=AsyncMock, return_value="openai translated"):
            result = await translator.translate("Hello world test text", target_language="zh-CN", source_language="en")
        assert result == "openai translated"

    @pytest.mark.asyncio
    async def test_translate_with_google(self):
        translator = self._make_translator()
        with patch("deep_translator.GoogleTranslator") as mock_gt:
            mock_gt.return_value.translate.return_value = "谷歌翻译"
            result = await translator._translate_with_google("Hello world", "zh-CN")
        assert result == "谷歌翻译"

    @pytest.mark.asyncio
    async def test_translate_with_google_exception(self):
        translator = self._make_translator()
        with patch("deep_translator.GoogleTranslator", side_effect=Exception("service down")):
            result = await translator._translate_with_google("Hello", "zh-CN")
        assert result is None

    @pytest.mark.asyncio
    async def test_translate_with_google_en_target(self):
        translator = self._make_translator()
        with patch("deep_translator.GoogleTranslator") as mock_gt:
            mock_gt.return_value.translate.return_value = "English translation"
            result = await translator._translate_with_google("你好世界", "en")
        assert result == "English translation"
        mock_gt.assert_called_with(source="auto", target="en")

    @pytest.mark.asyncio
    async def test_translate_with_google_zh_tw(self):
        translator = self._make_translator()
        with patch("deep_translator.GoogleTranslator") as mock_gt:
            mock_gt.return_value.translate.return_value = "繁體中文"
            result = await translator._translate_with_google("Hello", "zh-TW")
        assert result == "繁體中文"
        mock_gt.assert_called_with(source="auto", target="zh-TW")

    @pytest.mark.asyncio
    async def test_translate_with_runtime_none(self):
        translator = self._make_translator()
        result = await translator._translate_with_runtime("text", "zh-CN", None)
        assert result is None

    @pytest.mark.asyncio
    async def test_translate_with_runtime_success(self):
        from app.ai.provider import ModelRuntime

        translator = self._make_translator()
        runtime = ModelRuntime(provider="ollama", model="llama", api_base="http://localhost:11434")
        translator.model_client.generate_text = AsyncMock(return_value="translated")
        result = await translator._translate_with_runtime("text", "zh-CN", runtime)
        assert result == "translated"

    @pytest.mark.asyncio
    async def test_translate_with_runtime_exception(self):
        from app.ai.provider import ModelRuntime

        translator = self._make_translator()
        runtime = ModelRuntime(provider="ollama", model="llama", api_base="http://localhost:11434")
        translator.model_client.generate_text = AsyncMock(side_effect=Exception("timeout"))
        result = await translator._translate_with_runtime("text", "en", runtime)
        assert result is None

    def test_get_async_openai_client_no_key_raises(self):
        translator = self._make_translator()
        with pytest.raises(ValueError, match="API key"):
            translator._get_async_openai_client(api_key=None, api_base=None)

    def test_get_async_openai_client_caching(self):
        translator = self._make_translator()
        with patch("openai.AsyncOpenAI") as mock_openai:
            mock_openai.return_value = MagicMock()
            c1 = translator._get_async_openai_client(api_key="k1", api_base=None)
            c2 = translator._get_async_openai_client(api_key="k1", api_base=None)
            assert c1 is c2
            assert mock_openai.call_count == 1


class TestTranslatorStandalone:

    def test_get_translation_settings_success(self):
        with patch("app.services.system_settings.get_system_settings_sync", return_value={"translation_model": {"provider": "ollama"}}):
            from app.processors.translator import get_translation_settings
            result = get_translation_settings()
        assert result == {"provider": "ollama"}

    def test_get_translation_settings_exception(self):
        with patch("app.services.system_settings.get_system_settings_sync", side_effect=Exception("no db")):
            from app.processors.translator import get_translation_settings
            result = get_translation_settings()
        assert result == {}

    def test_get_translation_settings_not_dict(self):
        with patch("app.services.system_settings.get_system_settings_sync", return_value={"translation_model": "invalid"}):
            from app.processors.translator import get_translation_settings
            result = get_translation_settings()
        assert result == {}

    def test_is_translation_cloud_fallback_enabled_true(self):
        with patch("app.services.system_settings.get_system_settings_sync", return_value={"translation_cloud_fallback_enabled": True}):
            from app.processors.translator import is_translation_cloud_fallback_enabled
            assert is_translation_cloud_fallback_enabled() is True

    def test_is_translation_cloud_fallback_enabled_false(self):
        with patch("app.services.system_settings.get_system_settings_sync", return_value={}):
            from app.processors.translator import is_translation_cloud_fallback_enabled
            assert is_translation_cloud_fallback_enabled() is False

    def test_is_translation_cloud_fallback_exception(self):
        with patch("app.services.system_settings.get_system_settings_sync", side_effect=Exception("err")):
            from app.processors.translator import is_translation_cloud_fallback_enabled
            assert is_translation_cloud_fallback_enabled() is False

    def test_get_translation_cloud_fallback_openai_settings(self):
        sys_settings = {
            "translation_model": {"fallback_model": "gpt-4", "fallback_api_key": "k1"},
            "ai_model": {"model": "gpt-3.5", "api_key": "k2", "api_base": "https://api.openai.com"},
        }
        with patch("app.services.system_settings.get_system_settings_sync", return_value=sys_settings):
            from app.processors.translator import get_translation_cloud_fallback_openai_settings
            result = get_translation_cloud_fallback_openai_settings()
        assert result["model"] == "gpt-4"
        assert result["api_key"] == "k1"

    def test_get_translation_cloud_fallback_openai_settings_defaults(self):
        sys_settings = {"translation_model": {}, "ai_model": {}}
        with patch("app.services.system_settings.get_system_settings_sync", return_value=sys_settings):
            from app.processors.translator import get_translation_cloud_fallback_openai_settings
            result = get_translation_cloud_fallback_openai_settings()
        assert result["model"] == "gpt-4o-mini"
        assert result["provider"] == "openai"

    def test_get_translation_cloud_fallback_openai_settings_exception(self):
        with patch("app.services.system_settings.get_system_settings_sync", side_effect=Exception("err")):
            from app.processors.translator import get_translation_cloud_fallback_openai_settings
            result = get_translation_cloud_fallback_openai_settings()
        assert result["model"] == "gpt-4o-mini"
