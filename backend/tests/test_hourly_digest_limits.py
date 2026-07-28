from datetime import datetime
import asyncio

from app.domains.enrich.hourly import synthesis as digest_synthesis
from app.domains.enrich.hourly import tasks as digest_tasks
from app.domains.enrich.hourly import text_utils as digest_text


def _cluster_item(idx: int) -> dict:
    return {
        "topic": f"topic-{idx}",
        "score": 10 - idx,
        "items": [
            {
                "source_name": f"source-{idx}",
                "source_url": f"https://source-{idx}.example.com",
                "article_url": f"https://article-{idx}.example.com",
                "original_title": f"original-{idx}",
                "summary": f"summary-{idx}",
            }
        ],
    }


def test_digest_limits_are_read_from_system_settings(monkeypatch):
    monkeypatch.setattr(
        digest_text,
        "get_system_settings_sync",
        lambda: {"limits": {"max_hourly_digest_input_items": 360, "max_digest_candidates": 8}},
    )

    limits = digest_tasks._get_digest_limits()
    assert limits["max_input_items"] == 360
    assert limits["max_candidates"] == 8


def test_build_prompt_respects_candidate_limit():
    clusters = [_cluster_item(1), _cluster_item(2), _cluster_item(3)]
    prompt = digest_tasks._build_prompt("测试简报", clusters, candidate_limit=2)

    assert "1. 事件主题=topic-1" in prompt
    assert "2. 事件主题=topic-2" in prompt
    assert "3. 事件主题=topic-3" not in prompt


def test_build_fallback_digest_contains_original_titles_and_sources():
    clusters = [_cluster_item(1), _cluster_item(2)]

    body = digest_tasks._build_fallback_digest(
        "测试简报",
        clusters,
        candidate_limit=1,
        reason="AI 不可用，已回退。",
    )

    assert "## 测试简报" in body
    assert "### 重点" in body
    assert "**original-1**" in body
    assert "（来源：[source-1](https://article-1.example.com) [点击查看原文](https://article-1.example.com)）" in body
    assert "topic-2" not in body


def test_parse_generated_digest_item_returns_structured_item():
    cluster = _cluster_item(1)

    item = digest_tasks._parse_generated_digest_item(
        "分类：科技\n标题：苹果强化软硬件整合\n摘要：苹果继续依靠芯片、系统与硬件一体化能力巩固竞争力，并将这种整合模式延伸到下一阶段产品布局。",
        cluster,
    )

    assert item == {
        "category": "科技",
        "title": "苹果强化软硬件整合",
        "summary": "苹果继续依靠芯片、系统与硬件一体化能力巩固竞争力，并将这种整合模式延伸到下一阶段产品布局。",
        "source_name": "source-1",
        "article_url": "https://article-1.example.com",
        "local_reader_path": "",
    }


def test_build_digest_from_items_groups_sections_and_sources():
    body = digest_tasks._build_digest_from_items(
        "测试简报",
        [
            {
                "category": "科技",
                "title": "事件一",
                "summary": "摘要一",
                "source_name": "source-a",
                "article_url": "https://example.com/a",
            },
            {
                "category": "AI",
                "title": "事件二",
                "summary": "摘要二",
                "source_name": "source-b",
                "article_url": "https://example.com/b",
            },
        ],
    )

    assert "## 测试简报" in body
    assert "### 科技" in body
    assert "### AI" in body
    assert "**事件一**" in body
    assert "摘要二（来源：[source-b](https://example.com/b) [点击查看原文](https://example.com/b)）" in body


def test_build_hourly_briefing_digest_uses_redesigned_sections():
    body = digest_tasks._build_hourly_briefing_digest(
        "7 月 8 日 10 时简报",
        [
            {
                "section": "need_to_know",
                "title": "模型政策更新",
                "what_happened": "监管机构发布了新的模型政策。",
                "why_matters": "这是高优先级政策信号。",
                "source_names": ["Official"],
                "local_reader_path": "/reader/abc",
                "importance_score": 82.0,
            },
            {
                "section": "brewing",
                "title": "芯片出口传闻",
                "new_signal": "多家媒体提到新限制正在讨论。",
                "missing_confirmation": "还缺官方文件。",
                "source_names": ["Wire"],
                "local_reader_path": "/reader/def",
            },
            {
                "section": "later",
                "title": "产品小更新",
                "source_names": ["Blog"],
                "local_reader_path": "/reader/ghi",
                "importance_score": 61.0,
            },
        ],
    )

    assert "一句话：过去一小时真正值得注意的是，模型政策更新。" in body
    assert "### 需要你现在知道" in body
    assert "发生了什么：监管机构发布了新的模型政策。" in body
    assert "### 正在发酵" in body
    assert "还缺什么确认：还缺官方文件。" in body
    assert "### 可稍后看" in body
    assert "- [产品小更新](/reader/ghi)（Blog，重要性 61）" in body


def test_llm_synthesis_disables_reasoning_and_caps_output():
    calls = []

    class _FakeClient:
        async def generate_text(self, runtime, **kwargs):
            calls.append(kwargs)
            return "ok"

    class _Runtime:
        max_tokens = 2400

    result = asyncio.run(
        digest_tasks._llm_synthesize_hourly_digest(
            _FakeClient(),
            _Runtime(),
            title="7 月 28 日 9 时简报",
            materials="### 事件 1",
            task_prompt="只写最终简报。",
        )
    )

    assert result == "ok"
    assert calls[0]["no_think"] is True
    assert calls[0]["max_tokens"] == 2400


def test_localize_fallback_clusters_translates_primary_items(monkeypatch):
    class _FakeTranslator:
        def is_chinese(self, text: str) -> bool:
            return False

        async def translate(self, text: str, target_language: str = "zh-CN"):
            return f"译文：{text}"

    monkeypatch.setattr(digest_synthesis, "Translator", lambda: _FakeTranslator())

    clusters = [_cluster_item(1)]
    asyncio.run(digest_tasks._localize_fallback_clusters(clusters, candidate_limit=1))

    primary = clusters[0]["items"][0]
    assert primary["translated_title"] == "译文：original-1"
    assert primary["translated_summary"] == "译文：summary-1"


def test_is_valid_digest_format_accepts_synthesized_reader_links():
    title = "3 月 31 日 19 时简报"
    body = (
        f"## {title}\n\n"
        "一句话：本小时最值得关注的动态集中在政策与科技交叉领域。\n\n"
        "### 需要你现在知道\n\n"
        "[详情](/reader/abc) 显示多方信息正在收敛。\n\n"
        "### 正在发酵\n\n"
        "暂无。\n\n"
        "### 可稍后看\n\n"
        "- [延伸](/reader/def)"
    )
    assert digest_tasks._is_valid_digest_format(body, expected_title=title)


def test_parse_selection_ids_filters_and_caps():
    valid = {"a", "b", "c"}
    raw = '{"ids": ["b", "x", "a", "b"]}'
    assert digest_tasks._parse_selection_ids(raw, valid, max_n=2) == ["b", "a"]


def test_classify_digest_category_avoids_false_positive_substring_matches():
    assert digest_tasks._classify_digest_category("Airbnb is introducing a private car pick-up service") != "AI"
    assert digest_tasks._classify_digest_category("Raspberry Pi reports 2025 revenue up 25% YoY") != "汽车"


def test_completed_hour_digest_uses_window_end_hour_for_title():
    now = datetime(2026, 3, 31, 19, 20, tzinfo=digest_tasks.SYSTEM_TZ)
    start_local, end_local, _, _ = digest_tasks._compute_digest_window(now)

    assert start_local.hour == 18
    assert end_local.hour == 19
    assert digest_tasks._format_digest_title(end_local) == "3 月 31 日 19 时简报"


def test_three_hour_digest_window_uses_completed_boundary():
    now = datetime(2026, 3, 31, 19, 20, tzinfo=digest_tasks.SYSTEM_TZ)
    start_local, end_local, _, _ = digest_tasks._compute_digest_window(now, window_hours=3)

    assert start_local.hour == 15
    assert end_local.hour == 18
    assert digest_tasks._format_digest_title(end_local, window_hours=3) == "3 月 31 日 15-18 时简报"
