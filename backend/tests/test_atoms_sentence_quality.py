"""Tests for candidate sentence quality filtering."""

from __future__ import annotations

from app.domains.atoms.extractor.sentence_split import (
    filter_candidate_sentences,
    sentence_quality_reason,
)
from app.domains.ingest.summary_clean import clean_for_atomization


def test_short_english_label_rejected():
    assert sentence_quality_reason("Arguments:") is not None
    assert sentence_quality_reason("Basic Commands") is not None


def test_title_case_phrase_rejected():
    assert sentence_quality_reason("Global Cloud Native Computing Foundation Summit") == "title_like"


def test_short_cjk_rejected():
    assert sentence_quality_reason("华为发布。") == "short_cjk"


def test_code_like_rejected():
    assert sentence_quality_reason("const x = foo(bar)[0]; return {a: 1};") == "code_like"


def test_boilerplate_rejected():
    sentence = "广告声明：文内含有的对外跳转链接，用于传递更多信息，节省甄别时间。"
    assert sentence_quality_reason(sentence) == "boilerplate"


def test_occurrences_fragment_rejected():
    assert sentence_quality_reason("9 occurrences.") is not None


def test_substantive_cjk_sentence_kept():
    sentence = "华为于2026年5月18日在深圳发布了全新旗舰芯片麒麟X1，面向高端智能手机市场。"
    assert sentence_quality_reason(sentence) is None


def test_substantive_english_sentence_kept():
    sentence = "OpenAI announced a new model that reached state of the art results on benchmarks."
    assert sentence_quality_reason(sentence) is None


def test_filter_candidate_sentences_stats():
    sentences = [
        "Arguments:",
        "9 occurrences.",
        "华为于2026年5月18日在深圳发布了全新旗舰芯片麒麟X1，面向高端智能手机市场。",
    ]
    kept, stats = filter_candidate_sentences(sentences)
    assert len(kept) == 1
    assert sum(stats.values()) == 2


def test_clean_for_atomization_drops_boilerplate_and_code():
    text = (
        "华为于2026年5月18日在深圳发布了全新旗舰芯片麒麟X1，面向高端智能手机市场。\n"
        "广告声明：文内含有的对外跳转链接，用于传递更多信息。\n"
        "```\nprint('hi')\n```\n"
    )
    cleaned = clean_for_atomization(text)
    assert "麒麟X1" in cleaned
    assert "广告声明" not in cleaned
    assert "print" not in cleaned
