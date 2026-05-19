from __future__ import annotations

import pytest

from app.services.keyword_rules import (
    build_equivalent_terms,
    compute_stored_equivalent_terms,
    dedupe_keywords_case_insensitive,
    merge_equivalent_term_lists,
    normalize_manual_equivalent_terms,
)


def test_dedupe_keywords_case_insensitive_preserves_first_value():
    unique_values, skipped_values = dedupe_keywords_case_insensitive(
        ["AI", "ai", "OpenAI", "openai", "Agent"]
    )

    assert unique_values == ["AI", "OpenAI", "Agent"]
    assert skipped_values == ["ai", "openai"]


@pytest.mark.asyncio
async def test_build_equivalent_terms_uses_public_fallback_for_short_keywords(monkeypatch):
    async def _fake_model_translate(*_args, **_kwargs):
        return None

    async def _fake_public_translate(keyword: str, target_language: str) -> str | None:
        if keyword == "人工智能" and target_language == "en":
            return "artificial intelligence"
        return None

    monkeypatch.setattr("app.services.keyword_rules._translation_cache._entries", {})
    monkeypatch.setattr("app.processors.translator.Translator.translate", _fake_model_translate)
    monkeypatch.setattr(
        "app.services.keyword_rules._translate_keyword_via_public_endpoint",
        _fake_public_translate,
    )

    equivalents = await build_equivalent_terms("人工智能")

    assert equivalents == ["artificial intelligence"]


@pytest.mark.asyncio
async def test_build_equivalent_terms_skips_regex(monkeypatch):
    equivalents = await build_equivalent_terms(r"AI|Agent", match_type="regex")

    assert equivalents == []


@pytest.mark.asyncio
async def test_build_equivalent_terms_includes_static_aliases(monkeypatch):
    async def _fake_model_translate(*_args, **_kwargs):
        return None

    async def _fake_public_translate(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.processors.translator.Translator.translate", _fake_model_translate)
    monkeypatch.setattr(
        "app.services.keyword_rules._translate_keyword_via_public_endpoint",
        _fake_public_translate,
    )

    equivalents = await build_equivalent_terms("GPT")

    assert "生成式预训练变换器" in equivalents


def test_merge_equivalent_term_lists_manual_first_dedupes_auto():
    merged = merge_equivalent_term_lists(["Meta"], ["meta", "元宇宙"])
    assert merged == ["Meta", "元宇宙"]


def test_normalize_manual_equivalent_terms_drops_exact_main_and_dedupes():
    out = normalize_manual_equivalent_terms(["苹果", "Apple", "苹果"], main_keyword="苹果")
    assert out == ["Apple"]


def test_normalize_manual_equivalent_terms_keeps_case_variants_not_exact_duplicate():
    """Regression: main 'openclaw' must not drop manual 'OpenClaw' (was dropped by casefold identity)."""
    out = normalize_manual_equivalent_terms(["openclaw", "OpenClaw", "OPENCLAW"], main_keyword="openclaw")
    assert out == ["OpenClaw"]


@pytest.mark.asyncio
async def test_compute_stored_equivalent_terms_manual_only_skips_auto(monkeypatch):
    async def _boom(*_a, **_k):
        raise AssertionError("auto should not run")

    monkeypatch.setattr("app.services.keyword_rules.build_equivalent_terms", _boom)

    out = await compute_stored_equivalent_terms(
        "Meta",
        match_type="contains",
        manual_terms=["元宇宙"],
        include_auto=False,
    )
    assert out == ["元宇宙"]
