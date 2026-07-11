from datetime import date, datetime
from uuid import uuid4

import pytest

from app.domains.enrich.hourly.repository import build_hourly_digest_event_briefing_items
from app.domains.events.repository import stable_event_id
from app.models import Content, ContentEvent, ContentEventMembership, ContentEventSnapshot, HourlyDigest, Source
from app.models.source import SourceType


@pytest.mark.asyncio
async def test_today_highlights_use_digest_event_items_not_timeline(client, db_session):
    event_key = "event:policy:update"
    event_id = stable_event_id(event_key)
    digest = HourlyDigest(
        digest_date=date(2026, 7, 11),
        hour=9,
        title="9 时简报",
        summary="Summary",
        content_count=3,
        sources=["Official", "Analyst"],
        items_json=[
            {
                "event_key": event_key,
                "event_id": event_id,
                "section": "need_to_know",
                "content_id": str(uuid4()),
                "content_ids": [str(uuid4()), str(uuid4())],
                "title": "监管发布模型新规",
                "summary": "新规明确了模型备案要求。",
                "why_matters": "已有多个独立来源互相确认，优先级上升。",
                "new_signal": "官方版本发布。",
                "source_name": "Official",
                "source_names": ["Official", "Analyst"],
                "fetched_at": "2026-07-11T09:10:00Z",
                "importance_score": 88,
                "confidence_score": 91,
                "independent_source_count": 2,
            },
            {
                "event_key": "event:brewing",
                "event_id": stable_event_id("event:brewing"),
                "section": "brewing",
                "content_id": str(uuid4()),
                "title": "产业链出现跟进信号",
                "source_name": "Industry",
                "source_names": ["Industry", "Analyst"],
                "fetched_at": "2026-07-11T09:05:00Z",
                "importance_score": 72,
                "independent_source_count": 2,
            },
            {
                "event_key": "event:need-2",
                "event_id": stable_event_id("event:need-2"),
                "section": "need_to_know",
                "content_id": str(uuid4()),
                "title": "模型公司发布新版路线图",
                "source_name": "Company",
                "source_names": ["Company", "Media"],
                "fetched_at": "2026-07-11T09:01:00Z",
                "importance_score": 68,
                "independent_source_count": 2,
            },
            {
                "event_key": "event:later",
                "event_id": stable_event_id("event:later"),
                "section": "later",
                "content_id": str(uuid4()),
                "title": "低优先级事件",
                "source_name": "Other",
                "source_names": ["Other"],
                "importance_score": 95,
            },
        ],
    )
    db_session.add(digest)
    await db_session.commit()

    response = await client.get("/api/events/today-highlights", params={"date": "2026-07-11"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["date"] == "2026-07-11"
    assert [item["event_id"] for item in payload["items"]][:1] == [event_id]
    assert len(payload["items"]) == 3
    assert all(item["section"] != "later" for item in payload["items"])
    item = payload["items"][0]
    assert item["section"] == "need_to_know"
    assert item["independent_source_count"] == 2
    assert item["why_matters"] == "已有多个独立来源互相确认，优先级上升。"


@pytest.mark.asyncio
async def test_event_detail_returns_timeline_snapshots_and_feedback(client, db_session):
    source = Source(name="Official", type=SourceType.WEBSITE, url="https://official.example.com")
    event_id = stable_event_id("event:stable")
    content_a = Content(
        source=source,
        title="First report",
        summary="First summary",
        original_url="https://official.example.com/a",
        content_type="website",
        fetched_at=datetime(2026, 7, 11, 8, 0),
        publish_time=datetime(2026, 7, 11, 8, 0),
    )
    content_b = Content(
        source=source,
        title="Follow-up report",
        summary="Follow-up summary",
        original_url="https://official.example.com/b",
        content_type="website",
        fetched_at=datetime(2026, 7, 11, 9, 0),
        publish_time=datetime(2026, 7, 11, 9, 0),
    )
    db_session.add_all([source, content_a, content_b])
    await db_session.flush()
    event = ContentEvent(
        event_id=event_id,
        event_key="event:stable",
        title="Stable event",
        summary="Current conclusion",
        independent_source_count=1,
        source_names=["Official"],
        last_seen_at=datetime(2026, 7, 11, 9, 0),
        first_seen_at=datetime(2026, 7, 11, 8, 0),
        created_at=datetime(2026, 7, 11, 9, 0),
        updated_at=datetime(2026, 7, 11, 9, 0),
        metadata_={"why_matters": "Important"},
    )
    db_session.add_all(
        [
            event,
            ContentEventMembership(event_id=event_id, content_id=str(content_a.id), role="supporting"),
            ContentEventMembership(event_id=event_id, content_id=str(content_b.id), role="primary"),
            ContentEventSnapshot(
                event_id=event_id,
                version=1,
                title="Stable event",
                summary="Current conclusion",
                what_changed="Follow-up appeared",
                why_matters="Important",
                source_content_ids=[str(content_a.id), str(content_b.id)],
                created_at=datetime(2026, 7, 11, 9, 0),
            ),
        ]
    )
    await db_session.commit()

    feedback_response = await client.post(
        f"/api/events/{event_id}/feedback",
        json={"type": "event_wrong_merge", "content_id": str(content_a.id), "note": "不是同一事件"},
    )
    assert feedback_response.status_code == 200

    detail_response = await client.get(f"/api/events/{event_id}")

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["current_conclusion"] == "Current conclusion"
    assert [item["title"] for item in detail["timeline"]] == ["First report", "Follow-up report"]
    assert detail["timeline"][-1]["role"] == "primary"
    assert detail["snapshots"][0]["what_changed"] == "Follow-up appeared"
    assert detail["primary_reports"][0]["title"] == "Follow-up report"
    assert detail["independent_verification"][0]["title"] == "Official"
    assert detail["related_discussions"][0]["title"] == "关联讨论"
    assert detail["feedback"][0]["type"] == "event_wrong_merge"


def test_build_event_briefing_items_separates_event_from_duplicate_group():
    content_id = str(uuid4())
    event_items = build_hourly_digest_event_briefing_items(
        [
            {
                "event_key": "semantic-event",
                "event_score": 82,
                "corroboration_tier": "moderate",
                "independent_source_count": 2,
                "items": [
                    {
                        "content_id": content_id,
                        "title": "Policy update",
                        "summary": "Policy update summary",
                        "source_id": "official",
                        "source_name": "Official",
                        "source_url": "https://official.example.com",
                        "article_url": "https://official.example.com/policy",
                        "score_confidence": 0.8,
                        "metadata": {"duplicate_group_id": "article-duplicate"},
                    }
                ],
            }
        ],
        previous_event_index={},
    )

    assert event_items[0]["event_key"] == "semantic-event"
    assert event_items[0]["event_id"] == stable_event_id("semantic-event")
    assert event_items[0]["duplicate_group_id"] == "article-duplicate"
    assert event_items[0]["content_ids"] == [content_id]
    assert event_items[0]["why_matters"]
    assert event_items[0]["new_signal"]


@pytest.mark.asyncio
async def test_today_highlights_hide_when_fewer_than_three_qualified_events(client, db_session):
    digest = HourlyDigest(
        digest_date=date(2026, 7, 11),
        hour=9,
        title="9 时简报",
        summary="Summary",
        content_count=1,
        sources=["Official"],
        items_json=[
            {
                "event_key": "event:single",
                "event_id": stable_event_id("event:single"),
                "section": "need_to_know",
                "content_id": str(uuid4()),
                "title": "单条事件",
                "source_name": "Official",
                "source_names": ["Official"],
                "fetched_at": "2026-07-11T09:10:00Z",
                "importance_score": 90,
            }
        ],
    )
    db_session.add(digest)
    await db_session.commit()

    response = await client.get("/api/events/today-highlights", params={"date": "2026-07-11"})

    assert response.status_code == 200
    assert response.json()["items"] == []
