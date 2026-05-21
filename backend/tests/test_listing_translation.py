"""Tests for feed/listing title+summary translation."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domains.enrich.content.listing_translation import (
    content_needs_listing_translation,
    listing_translation_enabled,
    translate_listing_fields_async,
)


def test_listing_translation_enabled_requires_flags():
    with patch("app.config.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(ai_processing_enabled=True, enrich_translate_enabled=True)
        with patch(
            "app.platform.config.system_settings.get_system_settings_sync",
            return_value={"translation_enabled": True, "title_translation_enabled": True},
        ):
            assert listing_translation_enabled() is True

    with patch("app.config.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(ai_processing_enabled=False, enrich_translate_enabled=True)
        assert listing_translation_enabled() is False


def test_content_needs_listing_translation_for_english_title():
    with patch(
        "app.domains.enrich.content.listing_translation.listing_translation_enabled",
        return_value=True,
    ):
        translator = MagicMock()
        translator.is_chinese.return_value = False
        assert content_needs_listing_translation(
        title="Hello world news",
        summary=None,
        translated_title=None,
        translated_summary=None,
        translator=translator,
        )


def test_content_needs_listing_translation_skips_when_already_translated():
    with patch(
        "app.domains.enrich.content.listing_translation.listing_translation_enabled",
        return_value=True,
    ):
        translator = MagicMock()
        translator.is_chinese.side_effect = lambda text: "你好" in (text or "")
        assert not content_needs_listing_translation(
        title="Hello",
        summary="Summary",
        translated_title="你好世界",
        translated_summary="摘要内容足够长",
        translator=translator,
        )


@pytest.mark.asyncio
async def test_translate_listing_fields_async_persists_title_and_summary():
    content = MagicMock()
    content.id = "cid-1"
    content.title = "Breaking news"
    content.summary = "<p>Short summary text</p>"
    content.translated_title = None
    content.translated_summary = None
    content.full_content = "body"
    content.metadata_ = {}

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = content

    translator = MagicMock()
    translator.is_chinese.return_value = False
    translator.translate = AsyncMock(side_effect=["突发新闻", "简短摘要"])

    with patch(
        "app.domains.enrich.content.listing_translation.listing_translation_enabled",
        return_value=True,
    ), patch(
        "app.domains.enrich.content.listing_translation._is_valid_title_translation",
        side_effect=lambda _orig, cand: bool(cand),
    ), patch(
        "app.domains.enrich.content.listing_translation._is_valid_translation_text",
        side_effect=lambda cand: bool(cand),
    ), patch(
        "app.background.get_llm_semaphore",
    ) as mock_sem, patch(
        "app.database.SessionLocal",
        return_value=db,
    ), patch(
        "app.domains.enrich.content.listing_translation.Translator",
        return_value=translator,
    ), patch(
        "app.domains.enrich.content.listing_translation._resolve_target_language",
        return_value="zh-CN",
    ):
        mock_sem.return_value.__aenter__ = AsyncMock(return_value=None)
        mock_sem.return_value.__aexit__ = AsyncMock(return_value=False)

        ok = await translate_listing_fields_async("cid-1")

    assert ok is True
    assert content.translated_title == "突发新闻"
    assert content.translated_summary == "简短摘要"
    db.commit.assert_called_once()
