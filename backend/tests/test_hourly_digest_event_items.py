from datetime import datetime
from uuid import uuid4

from app.domains.enrich.hourly.repository import build_hourly_digest_event_items


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
