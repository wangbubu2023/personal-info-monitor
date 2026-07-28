"""Unit tests for :mod:`app.domains.enrich.hourly.text_utils`."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.domains.enrich.hourly.text_utils import (
    SYSTEM_TZ,
    classify_digest_category,
    clean_digest_text,
    coerce_limit_int,
    format_digest_title,
    is_valid_digest_format,
    local_to_utc_naive,
    normalize_digest_category,
    preferred_item_summary,
    preferred_item_title,
    strip_llm_reasoning,
    strip_ranking_internal,
)


class TestLocalToUtcNaive:
    def test_converts_shanghai_to_utc_naive(self):
        dt = datetime(2026, 4, 20, 12, 0, tzinfo=SYSTEM_TZ)
        assert local_to_utc_naive(dt) == datetime(2026, 4, 20, 4, 0)

    def test_already_utc(self):
        dt = datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc)
        assert local_to_utc_naive(dt) == datetime(2026, 4, 20, 12, 0)


class TestFormatDigestTitle:
    def test_title_format(self):
        dt = datetime(2026, 4, 20, 15, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        assert format_digest_title(dt) == "4 月 20 日 15 时简报"


class TestCoerceLimitInt:
    def test_returns_default_for_none(self):
        assert coerce_limit_int(None, default=10, min_value=1, max_value=100) == 10

    def test_clamps_to_max(self):
        assert coerce_limit_int(500, default=10, min_value=1, max_value=100) == 100

    def test_clamps_to_min(self):
        assert coerce_limit_int(-5, default=10, min_value=1, max_value=100) == 1

    def test_parses_string(self):
        assert coerce_limit_int("42", default=10, min_value=1, max_value=100) == 42

    def test_invalid_returns_default(self):
        assert coerce_limit_int("abc", default=10, min_value=1, max_value=100) == 10


class TestStripRankingInternal:
    def test_removes_underscore_prefixed(self):
        item = {"id": 1, "title": "T", "_rank": 5, "_score": 0.8}
        assert strip_ranking_internal(item) == {"id": 1, "title": "T"}


class TestCleanDigestText:
    def test_collapses_whitespace_and_escapes(self):
        assert clean_digest_text("  hello   &amp;   world  ") == "hello & world"

    def test_strips_single_byline_prefix(self):
        assert clean_digest_text("Reuters: Stocks rose today") == "Stocks rose today"

    def test_strips_combined_byline_prefix(self):
        assert clean_digest_text("Reuters / Bloomberg: Market update") == "Market update"


class TestPreferredItemHelpers:
    def test_title_prefers_translated(self):
        assert preferred_item_title({"translated_title": "译", "title": "en"}) == "译"

    def test_title_fallback_chain(self):
        assert preferred_item_title({"original_title": "orig"}) == "orig"
        assert preferred_item_title({}) == "未命名事件"

    def test_summary_truncates(self):
        summary = "x" * 200
        assert preferred_item_summary({"summary": summary}).endswith("...")

    def test_summary_placeholder_when_missing(self):
        assert "本次简报窗口" in preferred_item_summary({})


class TestNormalizeDigestCategory:
    def test_defaults_to_keypoint(self):
        assert normalize_digest_category("") == "重点"
        assert normalize_digest_category("  ") == "重点"

    def test_preserves_label(self):
        assert normalize_digest_category("AI") == "AI"


class TestClassifyDigestCategory:
    def test_ai_rule(self):
        assert classify_digest_category("OpenAI launches new LLM") == "AI"

    def test_automotive_rule(self):
        assert classify_digest_category("Tesla delivers 500k cars") == "汽车"

    def test_finance_rule(self):
        assert classify_digest_category("央行发布保险监管新规") == "金融"

    def test_tech_rule(self):
        assert classify_digest_category("New semiconductor startup raises funding") == "科技"

    def test_ascii_tokens_are_whole_word(self):
        # "ai" inside "airbnb" shouldn't match AI rule
        assert classify_digest_category("Airbnb lists new properties abroad") != "AI"

    def test_default_keypoint(self):
        assert classify_digest_category("Generic uncategorized text here") == "重点"


class TestIsValidDigestFormat:
    @staticmethod
    def _valid_body() -> str:
        return (
            "## 7 月 28 日 9 时简报\n\n"
            "一句话：过去一小时没有必须立即处理的重大变化。\n\n"
            "### 需要你现在知道\n\n"
            "本小时没有达到阈值的事件。\n\n"
            "### 正在发酵\n\n"
            "暂无。\n\n"
            "### 可稍后看\n\n"
            "- [补充材料](/reader/abc)"
        )

    def test_empty_rejected(self):
        assert not is_valid_digest_format("")
        assert not is_valid_digest_format("   ")

    def test_complete_contract_accepted(self, monkeypatch):
        monkeypatch.setenv("PIM_HOURLY_DIGEST_SKIP_FORMAT_VALIDATION", "false")
        assert is_valid_digest_format(
            self._valid_body(),
            expected_title="7 月 28 日 9 时简报",
        )

    def test_prompt_repetition_is_rejected(self, monkeypatch):
        monkeypatch.setenv("PIM_HOURLY_DIGEST_SKIP_FORMAT_VALIDATION", "false")
        body = (
            "首先，用户要求我生成简报。关键点：第一行必须是 `## 7 月 28 日 9 时简报`，"
            "还需要包含 `### 需要你现在知道`、来源：WSJ 和 /reader/abc。"
        )
        assert not is_valid_digest_format(body)

    def test_wrong_title_is_rejected(self, monkeypatch):
        monkeypatch.setenv("PIM_HOURLY_DIGEST_SKIP_FORMAT_VALIDATION", "false")
        assert not is_valid_digest_format(
            self._valid_body(),
            expected_title="7 月 28 日 10 时简报",
        )

    def test_reader_link_can_be_required(self, monkeypatch):
        monkeypatch.setenv("PIM_HOURLY_DIGEST_SKIP_FORMAT_VALIDATION", "false")
        without_reader = self._valid_body().replace("/reader/abc", "https://example.com/a")
        assert not is_valid_digest_format(
            without_reader,
            expected_title="7 月 28 日 9 时简报",
            require_reader_link=True,
        )

    def test_missing_or_reordered_sections_are_rejected(self, monkeypatch):
        monkeypatch.setenv("PIM_HOURLY_DIGEST_SKIP_FORMAT_VALIDATION", "false")
        body = self._valid_body().replace(
            "### 正在发酵",
            "### 其他分类",
        )
        assert not is_valid_digest_format(body)

    def test_meta_reasoning_inside_markdown_is_rejected(self, monkeypatch):
        monkeypatch.setenv("PIM_HOURLY_DIGEST_SKIP_FORMAT_VALIDATION", "false")
        body = self._valid_body().replace(
            "暂无。",
            "我需要先权衡这些候选事件。",
        )
        assert not is_valid_digest_format(body)

    def test_plain_text_rejected_when_validation_enabled(self, monkeypatch):
        monkeypatch.setenv("PIM_HOURLY_DIGEST_SKIP_FORMAT_VALIDATION", "false")
        assert not is_valid_digest_format("just some plain paragraph")

    def test_plain_text_accepted_when_validation_skipped(self, monkeypatch):
        monkeypatch.setenv("PIM_HOURLY_DIGEST_SKIP_FORMAT_VALIDATION", "true")
        assert is_valid_digest_format("just some plain paragraph")


class TestStripLlmReasoning:

    def test_removes_tagged_reasoning_and_keeps_final_digest(self):
        body = (
            "<think>我需要先分析提示词。</think>\n"
            + TestIsValidDigestFormat._valid_body()
        )
        assert strip_llm_reasoning(body).startswith("## 7 月 28 日 9 时简报")
