from datetime import datetime
from uuid import uuid4

from app.domains.enrich.hourly.repository import (
    build_hourly_digest_event_briefing_items,
    build_hourly_digest_event_items,
    filter_hourly_digest_event_items,
)


def test_build_hourly_digest_event_items_is_compact_and_structured():
    content_id = str(uuid4())
    event_items = build_hourly_digest_event_items(
        [
            {
                "content_id": content_id,
                "title": "Original title",
                "translated_title": "Translated title",
                "summary": "Summary " * 80,
                "translated_summary": "",
                "source_name": "Example",
                "source_url": "https://example.com",
                "article_url": "https://example.com/story",
                "publish_time": datetime(2026, 7, 2, 1, 2, 3),
                "fetched_at": datetime(2026, 7, 2, 1, 3, 0),
                "final_score": "91.5",
                "lane": "must_read",
                "metadata": {"duplicate_group_id": "title:abc"},
            }
        ]
    )

    assert event_items == [
        {
            "content_id": content_id,
            "title": "Translated title",
            "summary": ("Summary " * 80)[:300],
            "source_name": "Example",
            "source_url": "https://example.com",
            "url": "https://example.com/story",
            "publish_time": "2026-07-02T01:02:03Z",
            "fetched_at": "2026-07-02T01:03:00Z",
            "score": 91.5,
            "lane": "must_read",
            "duplicate_group_id": "title:abc",
        }
    ]


def test_build_hourly_digest_event_briefing_items_adds_scores_and_section():
    content_id = str(uuid4())
    event_items = build_hourly_digest_event_briefing_items(
        [
            {
                "event_key": "event-1",
                "event_score": 82.4,
                "corroboration_tier": "moderate",
                "independent_source_count": 2,
                "items": [
                    {
                        "content_id": content_id,
                        "title": "Major model policy update",
                        "summary": "A regulator published a new model policy update.",
                        "source_id": "source-a",
                        "source_name": "Official",
                        "source_url": "https://official.example.com",
                        "article_url": "https://official.example.com/policy",
                        "publish_time": datetime(2026, 7, 2, 1, 2, 3),
                        "fetched_at": datetime(2026, 7, 2, 1, 3, 0),
                        "score_confidence": 0.88,
                        "fulltext_status": "full",
                        "lane": "policy",
                        "metadata": {"duplicate_group_id": "title:policy"},
                    }
                ],
                "topic": "Major model policy update",
            }
        ],
        previous_event_index={},
    )

    assert event_items[0]["event_key"] == "event-1"
    assert event_items[0]["section"] == "need_to_know"
    assert event_items[0]["importance_score"] == 82.4
    assert event_items[0]["incremental_score"] >= 70
    assert event_items[0]["confidence_score"] == 88
    assert event_items[0]["local_reader_path"] == f"/reader/{content_id}"
    assert event_items[0]["source_names"] == ["Official"]


def test_low_importance_single_source_event_stays_in_later_section():
    content_id = str(uuid4())
    event_items = build_hourly_digest_event_briefing_items(
        [
            {
                "event_key": "event-low",
                "event_score": 14,
                "corroboration_tier": "single_low",
                "independent_source_count": 1,
                "items": [
                    {
                        "content_id": content_id,
                        "title": "A minor update",
                        "summary": "A small but factual update with enough supporting detail.",
                        "source_name": "Example",
                        "source_url": "https://example.com",
                        "article_url": "https://example.com/minor",
                        "score_confidence": 0.48,
                    }
                ],
            }
        ]
    )

    assert event_items[0]["section"] == "later"


def test_filter_event_items_removes_empty_and_comments_placeholders():
    items = [
        {"title": "Title only story", "summary": None},
        {"title": "Show HN: Example", "summary": "Comments"},
        {"title": "Substantive report", "summary": "A regulator published a detailed policy update."},
    ]

    assert filter_hourly_digest_event_items(items) == [items[2]]
