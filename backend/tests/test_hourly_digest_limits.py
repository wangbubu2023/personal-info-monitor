from datetime import datetime
import asyncio

from app.tasks import hourly_digest_tasks as digest_tasks


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
        digest_tasks,
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


def test_localize_fallback_clusters_translates_primary_items(monkeypatch):
    class _FakeTranslator:
        def is_chinese(self, text: str) -> bool:
            return False

        async def translate(self, text: str, target_language: str = "zh-CN"):
            return f"译文：{text}"

    monkeypatch.setattr(digest_tasks, "Translator", lambda: _FakeTranslator())

    clusters = [_cluster_item(1)]
    asyncio.run(digest_tasks._localize_fallback_clusters(clusters, candidate_limit=1))

    primary = clusters[0]["items"][0]
    assert primary["translated_title"] == "译文：original-1"
    assert primary["translated_summary"] == "译文：summary-1"


def test_classify_digest_category_avoids_false_positive_substring_matches():
    assert digest_tasks._classify_digest_category("Airbnb is introducing a private car pick-up service") != "AI"
    assert digest_tasks._classify_digest_category("Raspberry Pi reports 2025 revenue up 25% YoY") != "汽车"


def test_completed_hour_digest_uses_window_end_hour_for_title():
    now = datetime(2026, 3, 31, 19, 20, tzinfo=digest_tasks.SYSTEM_TZ)
    start_local, end_local, _, _ = digest_tasks._compute_digest_window(now)

    assert start_local.hour == 18
    assert end_local.hour == 19
    assert digest_tasks._format_digest_title(end_local) == "3 月 31 日 19 时简报"
