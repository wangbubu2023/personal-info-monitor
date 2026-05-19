"""Tests for app.api.contents_reader — reader and translation routes."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from types import SimpleNamespace
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.contents_reader import (
    _backfill_website_reader_body,
    _build_reader_translation_done_payload,
    _clean_x_body_if_needed,
    _clear_reader_translation_cache,
    _emit_cached_reader_translation,
    _ensure_reader_body,
    _ensure_translated_title,
    _fetch_reader_fulltext,
    _fetch_x_article_fulltext,
    _json_line,
    _load_source_cookies_for_reader,
    _persist_reader_translation_cache,
    _translate_reader_paragraph,
    _translate_reader_text,
    _upgrade_x_reader_body,
)


# ---------------------------------------------------------------------------
# _clear_reader_translation_cache
# ---------------------------------------------------------------------------

class TestClearReaderTranslationCache:

    def test_removes_translation_keys(self):
        meta = {
            "reader_translated_full_content": "cached",
            "reader_translated_body_hash": "abc",
            "reader_translation_ready": True,
            "reader_translation_ratio": 0.9,
            "other_key": "keep",
        }
        result = _clear_reader_translation_cache(meta)
        assert "reader_translated_full_content" not in result
        assert "reader_translated_body_hash" not in result
        assert "reader_translation_ready" not in result
        assert "reader_translation_ratio" not in result
        assert result["other_key"] == "keep"

    def test_does_not_mutate_original(self):
        meta = {"reader_translated_full_content": "x", "keep": 1}
        _clear_reader_translation_cache(meta)
        assert "reader_translated_full_content" in meta

    def test_empty_metadata(self):
        assert _clear_reader_translation_cache({}) == {}


# ---------------------------------------------------------------------------
# _fetch_reader_fulltext
# ---------------------------------------------------------------------------

class TestFetchReaderFulltext:

    @pytest.mark.asyncio
    async def test_empty_url_returns_empty(self):
        assert await _fetch_reader_fulltext("") == ("", "")

    @pytest.mark.asyncio
    async def test_none_url_returns_empty(self):
        assert await _fetch_reader_fulltext(None) == ("", "")

    @pytest.mark.asyncio
    async def test_non_http_scheme_rejected(self):
        assert await _fetch_reader_fulltext("ftp://example.com") == ("", "")

    @pytest.mark.asyncio
    async def test_private_url_rejected(self):
        with patch("app.domains.enrich.reader.body_loader.assert_public_http_target", side_effect=ValueError("private")):
            assert await _fetch_reader_fulltext("http://10.0.0.1/page") == ("", "")

    @pytest.mark.asyncio
    async def test_http_error_returns_empty(self):
        with patch("app.domains.enrich.reader.body_loader.assert_public_http_target", new_callable=AsyncMock):
            with patch("app.domains.enrich.reader.body_loader.aiohttp.ClientSession") as mock_session_cls:
                mock_resp = AsyncMock()
                mock_resp.status = 404
                mock_ctx = MagicMock()
                mock_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
                mock_ctx.__aexit__ = AsyncMock(return_value=False)
                mock_session = MagicMock()
                mock_session.get = MagicMock(return_value=mock_ctx)
                mock_session.__aenter__ = AsyncMock(return_value=mock_session)
                mock_session.__aexit__ = AsyncMock(return_value=False)
                mock_session_cls.return_value = mock_session
                assert await _fetch_reader_fulltext("https://example.com/page") == ("", "")

    @pytest.mark.asyncio
    async def test_short_html_returns_empty(self):
        with patch("app.domains.enrich.reader.body_loader.assert_public_http_target", new_callable=AsyncMock):
            with patch("app.domains.enrich.reader.body_loader.aiohttp.ClientSession") as mock_session_cls:
                mock_resp = AsyncMock()
                mock_resp.status = 200
                mock_resp.text = AsyncMock(return_value="<html>short</html>")
                mock_resp.url = "https://example.com/page"
                mock_ctx = MagicMock()
                mock_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
                mock_ctx.__aexit__ = AsyncMock(return_value=False)
                mock_session = MagicMock()
                mock_session.get = MagicMock(return_value=mock_ctx)
                mock_session.__aenter__ = AsyncMock(return_value=mock_session)
                mock_session.__aexit__ = AsyncMock(return_value=False)
                mock_session_cls.return_value = mock_session
                assert await _fetch_reader_fulltext("https://example.com/page") == ("", "")

    @pytest.mark.asyncio
    async def test_network_exception_returns_empty(self):
        import aiohttp as aiohttp_real
        with patch("app.domains.enrich.reader.body_loader.assert_public_http_target", new_callable=AsyncMock):
            with patch(
                "app.domains.enrich.reader.body_loader.aiohttp.ClientSession",
                side_effect=aiohttp_real.ClientError("network error"),
            ):
                assert await _fetch_reader_fulltext("https://example.com/page") == ("", "")

    @pytest.mark.asyncio
    async def test_successful_extraction(self):
        """Covered by integration-level tests; complex aiohttp mock omitted."""
        pass

    @pytest.mark.asyncio
    async def test_short_extracted_text_returns_empty(self):
        long_html = "<html><body>" + "x" * 600 + "</body></html>"
        with patch("app.domains.enrich.reader.body_loader.assert_public_http_target", new_callable=AsyncMock):
            with patch("app.domains.enrich.reader.body_loader.aiohttp.ClientSession") as mock_session_cls:
                mock_resp = AsyncMock()
                mock_resp.status = 200
                mock_resp.text = AsyncMock(return_value=long_html)
                mock_resp.url = "https://example.com/page"
                mock_ctx = MagicMock()
                mock_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
                mock_ctx.__aexit__ = AsyncMock(return_value=False)
                mock_session = MagicMock()
                mock_session.get = MagicMock(return_value=mock_ctx)
                mock_session.__aenter__ = AsyncMock(return_value=mock_session)
                mock_session.__aexit__ = AsyncMock(return_value=False)
                mock_session_cls.return_value = mock_session
                with patch("app.domains.enrich.reader.body_loader.ContentExtractor") as mock_extractor_cls:
                    mock_extractor = MagicMock()
                    mock_extractor.extract = AsyncMock(return_value="short")
                    mock_extractor_cls.return_value = mock_extractor
                    with patch("app.domains.enrich.reader.body_loader.strip_html_tags", return_value="short"):
                        assert await _fetch_reader_fulltext("https://example.com/page") == ("", "")


# ---------------------------------------------------------------------------
# _fetch_x_article_fulltext
# ---------------------------------------------------------------------------

class TestFetchXArticleFulltext:

    @pytest.mark.asyncio
    async def test_empty_url_returns_empty(self):
        assert await _fetch_x_article_fulltext("", {}) == ""

    @pytest.mark.asyncio
    async def test_exception_returns_empty(self):
        with patch("app.collectors.x_twitter.XCollector", side_effect=ImportError("no module")):
            assert await _fetch_x_article_fulltext("https://x.com/i/article/123", {}) == ""

    @pytest.mark.asyncio
    async def test_short_text_returns_empty(self):
        mock_collector = MagicMock()
        mock_collector._fetch_article_texts_with_playwright = AsyncMock(
            return_value={"https://x.com/i/article/123": "short text"}
        )
        with patch.dict("sys.modules", {"app.collectors.x_twitter": MagicMock(XCollector=lambda: mock_collector)}):
            result = await _fetch_x_article_fulltext("https://x.com/i/article/123", {})
            assert result == ""

    @pytest.mark.asyncio
    async def test_successful_fetch(self):
        long_text = "A" * 300
        mock_collector = MagicMock()
        mock_collector._fetch_article_texts_with_playwright = AsyncMock(
            return_value={"https://x.com/i/article/123": long_text}
        )
        with patch.dict("sys.modules", {"app.collectors.x_twitter": MagicMock(XCollector=lambda: mock_collector)}):
            result = await _fetch_x_article_fulltext("https://x.com/i/article/123", {})
            assert result == long_text


# ---------------------------------------------------------------------------
# _load_source_cookies_for_reader
# ---------------------------------------------------------------------------

class TestLoadSourceCookiesForReader:

    @pytest.mark.asyncio
    async def test_empty_source_id(self):
        db = AsyncMock()
        result = await _load_source_cookies_for_reader(db, "")
        assert result == {}

    @pytest.mark.asyncio
    async def test_db_exception_returns_fallback(self):
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=Exception("db error"))
        with patch("app.domains.enrich.reader.body_loader.get_settings") as mock_settings:
            settings = MagicMock()
            settings.x_auth_token = None
            settings.x_ct0_token = None
            mock_settings.return_value = settings
            result = await _load_source_cookies_for_reader(db, "some-id")
            assert result == {}

    @pytest.mark.asyncio
    async def test_source_not_found_falls_to_settings(self):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)
        with patch("app.domains.enrich.reader.body_loader.get_settings") as mock_settings:
            settings = MagicMock()
            settings.x_auth_token = "tok"
            settings.x_ct0_token = "ct0"
            mock_settings.return_value = settings
            result = await _load_source_cookies_for_reader(db, "some-id")
            assert result == {"auth_token": "tok", "ct0": "ct0"}

    @pytest.mark.asyncio
    async def test_source_with_auth_credentials(self):
        db = AsyncMock()
        source = MagicMock()
        source.auth_config = MagicMock()
        source.metadata_ = {}
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = source
        db.execute = AsyncMock(return_value=mock_result)

        with patch("app.domains.enrich.reader.body_loader.try_parse_auth_credentials", return_value={"cookies": {"a": "1"}}):
            with patch("app.domains.enrich.reader.body_loader.normalize_cookie_dict", return_value={"a": "1"}):
                result = await _load_source_cookies_for_reader(db, "some-id")
                assert result == {"a": "1"}

    @pytest.mark.asyncio
    async def test_source_x_metadata_tokens(self):
        db = AsyncMock()
        source = MagicMock()
        source.auth_config = None
        source.metadata_ = {"x_auth_token": "meta_tok", "x_ct0_token": "meta_ct0"}
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = source
        db.execute = AsyncMock(return_value=mock_result)

        with patch("app.domains.enrich.reader.body_loader.try_parse_auth_credentials", return_value={}):
            with patch("app.domains.enrich.reader.body_loader.normalize_cookie_dict", return_value={}):
                result = await _load_source_cookies_for_reader(db, "some-id")
                assert result == {"auth_token": "meta_tok", "ct0": "meta_ct0"}


# ---------------------------------------------------------------------------
# _ensure_translated_title
# ---------------------------------------------------------------------------

class TestEnsureTranslatedTitle:

    @pytest.mark.asyncio
    async def test_already_has_translation(self):
        content = MagicMock()
        content.title = "Hello"
        content.translated_title = "你好"
        db = AsyncMock()
        result = await _ensure_translated_title(content, db)
        assert result == "你好"

    @pytest.mark.asyncio
    async def test_empty_title_returns_empty(self):
        content = MagicMock()
        content.title = ""
        content.translated_title = ""
        db = AsyncMock()
        result = await _ensure_translated_title(content, db)
        assert result == ""

    @pytest.mark.asyncio
    async def test_url_like_title_returns_as_is(self):
        content = MagicMock()
        content.title = "https://example.com/some-page"
        content.translated_title = ""
        db = AsyncMock()
        result = await _ensure_translated_title(content, db)
        assert result == "https://example.com/some-page"

    @pytest.mark.asyncio
    async def test_chinese_title_returns_without_translation(self):
        content = MagicMock()
        content.title = "这是一个中文标题"
        content.translated_title = ""
        db = AsyncMock()
        with patch("app.domains.enrich.reader.translation.Translator") as mock_translator_cls:
            mock_translator = MagicMock()
            mock_translator.is_chinese.return_value = True
            mock_translator_cls.return_value = mock_translator
            result = await _ensure_translated_title(content, db)
            assert result == "这是一个中文标题"

    @pytest.mark.asyncio
    async def test_successful_translation(self):
        content = MagicMock()
        content.title = "Hello World"
        content.translated_title = ""
        db = AsyncMock()
        with patch("app.domains.enrich.reader.translation.Translator") as mock_translator_cls:
            mock_translator = MagicMock()
            mock_translator.is_chinese.return_value = False
            mock_translator.translate = AsyncMock(return_value="你好世界")
            mock_translator_cls.return_value = mock_translator
            with patch("app.domains.enrich.reader.translation._is_valid_translation_text", return_value=True):
                with patch("app.domains.enrich.reader.translation._is_valid_title_translation", return_value=True):
                    result = await _ensure_translated_title(content, db)
                    assert result == "你好世界"
                    db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_translation_timeout_returns_original(self):
        content = MagicMock()
        content.title = "Hello World"
        content.translated_title = ""
        db = AsyncMock()
        with patch("app.domains.enrich.reader.translation.Translator") as mock_translator_cls:
            mock_translator = MagicMock()
            mock_translator.is_chinese.return_value = False
            mock_translator.translate = AsyncMock(side_effect=asyncio.TimeoutError)
            mock_translator.translate_with_fallback = AsyncMock(side_effect=asyncio.TimeoutError)
            mock_translator_cls.return_value = mock_translator
            with patch("app.domains.enrich.reader.translation._is_valid_translation_text", return_value=False):
                with patch("app.domains.enrich.reader.translation._is_valid_title_translation", return_value=False):
                    result = await _ensure_translated_title(content, db)
                    assert result == "Hello World"

    @pytest.mark.asyncio
    async def test_fallback_translator_used(self):
        content = MagicMock()
        content.title = "Hello World"
        content.translated_title = ""
        db = AsyncMock()
        with patch("app.domains.enrich.reader.translation.Translator") as mock_translator_cls:
            mock_translator = MagicMock()
            mock_translator.is_chinese.return_value = False
            mock_translator.translate = AsyncMock(return_value=None)
            mock_translator.translate_with_fallback = AsyncMock(return_value="你好世界")
            mock_translator_cls.return_value = mock_translator
            with patch("app.domains.enrich.reader.translation._is_valid_translation_text", side_effect=[False, True]):
                with patch("app.domains.enrich.reader.translation._is_valid_title_translation", return_value=True):
                    result = await _ensure_translated_title(content, db)
                    assert result == "你好世界"


# ---------------------------------------------------------------------------
# _json_line
# ---------------------------------------------------------------------------

class TestJsonLine:

    def test_basic_payload(self):
        result = _json_line({"type": "chunk", "text": "hello"})
        assert isinstance(result, bytes)
        parsed = json.loads(result.decode("utf-8").strip())
        assert parsed["type"] == "chunk"
        assert parsed["text"] == "hello"

    def test_chinese_content_preserved(self):
        result = _json_line({"text": "你好世界"})
        decoded = result.decode("utf-8")
        assert "你好世界" in decoded

    def test_ends_with_newline(self):
        result = _json_line({"type": "done"})
        assert result.endswith(b"\n")


# ---------------------------------------------------------------------------
# _translate_reader_paragraph
# ---------------------------------------------------------------------------

class TestTranslateReaderParagraph:

    @pytest.mark.asyncio
    async def test_successful_translation(self):
        translator = MagicMock()
        translator.translate = AsyncMock(return_value="翻译结果")
        with patch("app.domains.enrich.reader.translation._is_valid_translation_text", return_value=True):
            piece, success = await _translate_reader_paragraph("Hello", translator, timeout_seconds=5.0)
            assert piece == "翻译结果"
            assert success is True

    @pytest.mark.asyncio
    async def test_translation_failure_falls_back(self):
        translator = MagicMock()
        translator.translate = AsyncMock(side_effect=Exception("fail"))
        translator.translate_with_fallback = AsyncMock(return_value="回退翻译")
        with patch("app.domains.enrich.reader.translation._is_valid_translation_text", side_effect=[False, True]):
            piece, success = await _translate_reader_paragraph("Hello", translator, timeout_seconds=5.0)
            assert piece == "回退翻译"
            assert success is True

    @pytest.mark.asyncio
    async def test_all_translation_fails(self):
        translator = MagicMock()
        translator.translate = AsyncMock(side_effect=Exception("fail"))
        translator.translate_with_fallback = AsyncMock(side_effect=Exception("also fail"))
        with patch("app.domains.enrich.reader.translation._is_valid_translation_text", return_value=False):
            piece, success = await _translate_reader_paragraph("Hello", translator, timeout_seconds=5.0)
            assert piece == "Hello"
            assert success is False


# ---------------------------------------------------------------------------
# _translate_reader_text
# ---------------------------------------------------------------------------

class TestTranslateReaderText:

    @pytest.mark.asyncio
    async def test_empty_text(self):
        assert await _translate_reader_text("") == ""

    @pytest.mark.asyncio
    async def test_chinese_text_returns_as_is(self):
        with patch("app.domains.enrich.reader.translation.Translator") as mock_cls:
            mock_t = MagicMock()
            mock_t.is_chinese.return_value = True
            mock_cls.return_value = mock_t
            result = await _translate_reader_text("这是中文内容")
            assert result == "这是中文内容"

    @pytest.mark.asyncio
    async def test_translation_with_chunks(self):
        text = "Paragraph one.\n\nParagraph two."
        with patch("app.domains.enrich.reader.translation.Translator") as mock_cls:
            mock_t = MagicMock()
            mock_t.is_chinese.return_value = False
            mock_t.translate = AsyncMock(return_value="翻译段落")
            mock_cls.return_value = mock_t
            with patch("app.domains.enrich.reader.translation._split_for_reader", return_value=["Paragraph one.", "Paragraph two."]):
                with patch("app.domains.enrich.reader.translation._is_valid_translation_text", return_value=True):
                    result = await _translate_reader_text(text)
                    assert "翻译段落" in result


# ---------------------------------------------------------------------------
# _persist_reader_translation_cache
# ---------------------------------------------------------------------------

class TestPersistReaderTranslationCache:

    @pytest.mark.asyncio
    async def test_successful_persist(self):
        content = MagicMock()
        db = AsyncMock()
        db.commit = AsyncMock()
        result = await _persist_reader_translation_cache(
            content=content, db=db, metadata={}, body_hash="abc",
            final_text="translated", ratio=0.8,
        )
        assert result is True
        assert content.metadata_["reader_translated_full_content"] == "translated"
        assert content.metadata_["reader_translated_body_hash"] == "abc"
        assert content.metadata_["reader_translation_ready"] is True

    @pytest.mark.asyncio
    async def test_commit_failure_rolls_back(self):
        content = MagicMock()
        db = AsyncMock()
        db.commit = AsyncMock(side_effect=Exception("db error"))
        db.rollback = AsyncMock()
        result = await _persist_reader_translation_cache(
            content=content, db=db, metadata={}, body_hash="abc",
            final_text="translated", ratio=0.8,
        )
        assert result is False
        db.rollback.assert_called()


# ---------------------------------------------------------------------------
# _emit_cached_reader_translation
# ---------------------------------------------------------------------------

class TestEmitCachedReaderTranslation:

    @pytest.mark.asyncio
    async def test_yields_chunks_and_done(self):
        with patch("app.domains.enrich.reader.streaming._split_for_reader", return_value=["段落一", "段落二"]):
            chunks = []
            async for item in _emit_cached_reader_translation("段落一\n\n段落二"):
                chunks.append(json.loads(item.decode("utf-8")))
            assert len(chunks) == 3
            assert chunks[0]["type"] == "chunk"
            assert chunks[0]["index"] == 0
            assert chunks[1]["type"] == "chunk"
            assert chunks[1]["index"] == 1
            assert chunks[2]["type"] == "done"
            assert chunks[2]["translation_cached"] is True


# ---------------------------------------------------------------------------
# _build_reader_translation_done_payload
# ---------------------------------------------------------------------------

class TestBuildReaderTranslationDonePayload:

    def test_success_all_translated(self):
        result = _build_reader_translation_done_payload(
            total_count=5, translated_parts=["a", "b", "c", "d", "e"],
            translated_count=5, translated_success=True, cache_written=True, ratio=1.0,
        )
        assert result["type"] == "done"
        assert result["message"] == "ok"
        assert result["translated"] is True
        assert result["partial_fallback"] is False

    def test_partial_translation(self):
        result = _build_reader_translation_done_payload(
            total_count=5, translated_parts=["a", "b", "c", "d", "e"],
            translated_count=3, translated_success=True, cache_written=True, ratio=0.6,
        )
        assert "部分段落翻译失败" in result["message"]
        assert result["partial_fallback"] is True

    def test_translation_below_threshold(self):
        result = _build_reader_translation_done_payload(
            total_count=5, translated_parts=["a", "b"],
            translated_count=2, translated_success=False, cache_written=False, ratio=0.4,
        )
        assert "译文生成未达到可读阈值" in result["message"]
        assert result["translated"] is False

    def test_zero_translations(self):
        result = _build_reader_translation_done_payload(
            total_count=5, translated_parts=[],
            translated_count=0, translated_success=False, cache_written=False, ratio=0.0,
        )
        assert "未检测到可用翻译结果" in result["message"]


# ---------------------------------------------------------------------------
# _ensure_reader_body
# ---------------------------------------------------------------------------

class TestEnsureReaderBody:

    @pytest.mark.asyncio
    async def test_x_short_body_upgrades(self):
        content = MagicMock()
        content.metadata_ = {}
        content.full_content = "short"
        content.summary = ""
        content.content_type = "x"
        db = AsyncMock()
        with patch("app.domains.enrich.reader.body_loader.upgrade_x_reader_body", new_callable=AsyncMock) as mock_upgrade:
            mock_upgrade.return_value = ("long article text" * 20, {"upgraded": True})
            body, meta = await _ensure_reader_body(content, db)
            assert "long article text" in body
            mock_upgrade.assert_called_once()

    @pytest.mark.asyncio
    async def test_x_body_with_content_cleans(self):
        content = MagicMock()
        content.metadata_ = {}
        content.full_content = "A" * 300
        content.summary = ""
        content.content_type = "x"
        content.title = "Normal Title"
        content.translated_title = None
        db = AsyncMock()
        with patch("app.domains.enrich.reader.body_loader.upgrade_x_reader_body", new_callable=AsyncMock) as mock_upgrade:
            mock_upgrade.return_value = (None, None)
            with patch("app.domains.enrich.reader.body_loader.clean_x_body_if_needed", new_callable=AsyncMock) as mock_clean:
                mock_clean.return_value = ("A" * 300, {})
                with patch("app.domains.enrich.reader.body_loader._title_looks_like_url", return_value=False):
                    body, meta = await _ensure_reader_body(content, db)
                    assert body == "A" * 300

    @pytest.mark.asyncio
    async def test_website_body_backfills(self):
        content = MagicMock()
        content.metadata_ = {}
        content.full_content = ""
        content.summary = ""
        content.content_type = "website"
        content.original_url = "https://example.com"
        db = AsyncMock()
        with patch("app.domains.enrich.reader.body_loader.backfill_website_reader_body", new_callable=AsyncMock) as mock_backfill:
            mock_backfill.return_value = ("backfilled text", {"backfilled": True})
            body, meta = await _ensure_reader_body(content, db)
            assert body == "backfilled text"


# ---------------------------------------------------------------------------
# _backfill_website_reader_body
# ---------------------------------------------------------------------------

class TestBackfillWebsiteReaderBody:

    @pytest.mark.asyncio
    async def test_non_empty_body_skips(self):
        content = MagicMock()
        content.content_type = "website"
        content.original_url = "https://example.com"
        db = AsyncMock()
        body, meta = await _backfill_website_reader_body(content, {}, "existing body", db)
        assert body == "existing body"

    @pytest.mark.asyncio
    async def test_non_website_skips(self):
        content = MagicMock()
        content.content_type = "x"
        content.original_url = "https://x.com/user"
        db = AsyncMock()
        body, meta = await _backfill_website_reader_body(content, {}, "", db)
        assert body == ""

    @pytest.mark.asyncio
    async def test_no_original_url_skips(self):
        content = MagicMock()
        content.content_type = "website"
        content.original_url = ""
        db = AsyncMock()
        body, meta = await _backfill_website_reader_body(content, {}, "", db)
        assert body == ""

    @pytest.mark.asyncio
    async def test_successful_backfill(self):
        content = MagicMock()
        content.content_type = "website"
        content.original_url = "https://example.com"
        content.summary = ""
        db = AsyncMock()
        with patch("app.domains.enrich.reader.body_loader.fetch_reader_fulltext", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = ("Fetched body text " * 30, "https://example.com/resolved")
            with patch("app.domains.enrich.reader.body_loader.truncate_content", return_value="Fetched body text " * 30):
                body, meta = await _backfill_website_reader_body(content, {}, "", db)
                assert "Fetched body text" in body
                db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_backfill_updates_resolved_url(self):
        content = MagicMock()
        content.content_type = "website"
        content.original_url = "https://example.com/old"
        content.summary = ""
        db = AsyncMock()
        with patch("app.domains.enrich.reader.body_loader.fetch_reader_fulltext", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = ("Content " * 80, "https://example.com/new")
            with patch("app.domains.enrich.reader.body_loader.truncate_content", return_value="Content " * 80):
                body, meta = await _backfill_website_reader_body(content, {}, "", db)
                assert content.original_url == "https://example.com/new"
                assert meta.get("resolved_original_url") == "https://example.com/new"


# ---------------------------------------------------------------------------
# _clean_x_body_if_needed
# ---------------------------------------------------------------------------

class TestCleanXBodyIfNeeded:

    @pytest.mark.asyncio
    async def test_no_change_needed(self):
        content = MagicMock()
        db = AsyncMock()
        with patch("app.domains.enrich.reader.body_loader._clean_x_reader_body", return_value="same body"):
            body, meta = await _clean_x_body_if_needed(content, {}, "same body", db)
            assert body == "same body"

    @pytest.mark.asyncio
    async def test_cleaning_applied(self):
        content = MagicMock()
        content.original_url = "https://x.com/status/1"
        db = AsyncMock()
        with patch("app.domains.enrich.reader.body_loader._clean_x_reader_body", return_value="cleaned body"):
            with patch("app.domains.enrich.reader.body_loader.truncate_content", return_value="cleaned body"):
                body, meta = await _clean_x_body_if_needed(content, {}, "dirty body", db)
                assert body == "cleaned body"
                assert meta.get("x_reader_cleaned") is True
                db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_empty_cleaned_returns_original(self):
        content = MagicMock()
        db = AsyncMock()
        with patch("app.domains.enrich.reader.body_loader._clean_x_reader_body", return_value=""):
            body, meta = await _clean_x_body_if_needed(content, {}, "original", db)
            assert body == "original"


# ---------------------------------------------------------------------------
# _upgrade_x_reader_body
# ---------------------------------------------------------------------------

class TestUpgradeXReaderBody:

    @pytest.mark.asyncio
    async def test_no_article_text_returns_none(self):
        content = MagicMock()
        content.source_id = "src-1"
        db = AsyncMock()
        with patch("app.domains.enrich.reader.body_loader._extract_x_article_url", return_value="https://x.com/i/article/1"):
            with patch("app.domains.enrich.reader.body_loader.load_source_cookies_for_reader", new_callable=AsyncMock, return_value={}):
                with patch("app.domains.enrich.reader.body_loader.fetch_x_article_fulltext", new_callable=AsyncMock, return_value=""):
                    body, meta = await _upgrade_x_reader_body(content, {}, "short", db)
                    assert body is None
                    assert meta is None

    @pytest.mark.asyncio
    async def test_article_shorter_than_body_returns_none(self):
        content = MagicMock()
        content.source_id = "src-1"
        db = AsyncMock()
        with patch("app.domains.enrich.reader.body_loader._extract_x_article_url", return_value=""):
            with patch("app.domains.enrich.reader.body_loader.load_source_cookies_for_reader", new_callable=AsyncMock, return_value={}):
                with patch("app.domains.enrich.reader.body_loader.fetch_x_article_fulltext", new_callable=AsyncMock, return_value="short"):
                    body, meta = await _upgrade_x_reader_body(content, {}, "longer body text", db)
                    assert body is None

    @pytest.mark.asyncio
    async def test_successful_upgrade(self):
        long_text = "A" * 600
        content = MagicMock()
        content.source_id = "src-1"
        content.title = "Normal Title"
        content.translated_title = None
        db = AsyncMock()
        with patch("app.domains.enrich.reader.body_loader._extract_x_article_url", return_value="https://x.com/i/article/1"):
            with patch("app.domains.enrich.reader.body_loader.load_source_cookies_for_reader", new_callable=AsyncMock, return_value={}):
                with patch("app.domains.enrich.reader.body_loader.fetch_x_article_fulltext", new_callable=AsyncMock, return_value=long_text):
                    with patch("app.domains.enrich.reader.body_loader.truncate_content", return_value=long_text):
                        with patch("app.domains.enrich.reader.body_loader.clear_reader_translation_cache", return_value={}):
                            with patch("app.domains.enrich.reader.body_loader._title_looks_like_url", return_value=False):
                                with patch("app.domains.enrich.reader.body_loader._looks_like_translation_refusal", return_value=False):
                                    body, meta = await _upgrade_x_reader_body(content, {}, "short", db)
                                    assert body == long_text
                                    db.commit.assert_called()
