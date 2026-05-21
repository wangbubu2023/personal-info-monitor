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
    def test_empty_rejected(self):
        assert not is_valid_digest_format("")
        assert not is_valid_digest_format("   ")

    def test_h3_with_source_accepted(self, monkeypatch):
        monkeypatch.setenv("PIM_HOURLY_DIGEST_SKIP_FORMAT_VALIDATION", "false")
        body = "### 标题\n正文\n来源：X"
        assert is_valid_digest_format(body)

    def test_h2_with_reader_link_accepted(self, monkeypatch):
        monkeypatch.setenv("PIM_HOURLY_DIGEST_SKIP_FORMAT_VALIDATION", "false")
        body = "## 标题\n" + ("一条比较长的正文 " * 10) + "\n/reader/abc"
        assert is_valid_digest_format(body)

    def test_plain_text_rejected_when_validation_enabled(self, monkeypatch):
        monkeypatch.setenv("PIM_HOURLY_DIGEST_SKIP_FORMAT_VALIDATION", "false")
        assert not is_valid_digest_format("just some plain paragraph")

    def test_plain_text_accepted_when_validation_skipped(self, monkeypatch):
        monkeypatch.setenv("PIM_HOURLY_DIGEST_SKIP_FORMAT_VALIDATION", "true")
        assert is_valid_digest_format("just some plain paragraph")
