from __future__ import annotations

from datetime import date, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from app.api.digest import _completed_hour_label_to_utc_window
from app.models import Content, HourlyDigest, Source
from app.models.source import SourceType
from app.utils.datetime import utcnow_naive

# Daily digest API treats the ``date`` query param as a calendar day in
# Asia/Shanghai (see digest_service / digest routes). Tests must align the
# requested date with that zone, not with naive UTC ``date.today()``.
_DIGEST_TZ = ZoneInfo("Asia/Shanghai")


def _digest_calendar_date(utc_naive) -> date:
    """Calendar day in Asia/Shanghai matching the digest API."""
    return utc_naive.replace(tzinfo=timezone.utc).astimezone(_DIGEST_TZ).date()


def _digest_date_param(utc_naive) -> str:
    return _digest_calendar_date(utc_naive).isoformat()


@pytest.mark.asyncio
async def test_daily_digest_filters_by_keyword_and_type(client, db_session):
    keyword_id = str(uuid4())
    website_source = Source(name="Example", type=SourceType.WEBSITE, url="https://example.com")
    x_source = Source(name="X", type=SourceType.X, url="https://x.com/example")
    now = utcnow_naive()
    website_content = Content(
        source=website_source,
        title="Website",
        summary="Web summary",
        original_url="https://example.com/article",
        content_type="website",
        fetched_at=now,
        publish_time=now,
        keyword_matches=[{"id": keyword_id, "name": "AI"}],
    )
    x_content = Content(
        source=x_source,
        title="Tweet",
        summary="X summary",
        original_url="https://x.com/example/status/1",
        content_type="x",
        fetched_at=now,
        publish_time=now,
        keyword_matches=[{"id": str(uuid4()), "name": "Other"}],
        read_status=True,
    )
    db_session.add_all([website_source, x_source, website_content, x_content])
    await db_session.commit()

    response = await client.get(
        "/api/digest",
        params=[
                ("date", _digest_date_param(now)),
                ("unread_only", "false"),
                ("source_types", "website"),
                ("keyword_ids", keyword_id),
            ],
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_items"] == 1
    assert payload["categories"]["websites"]["count"] == 1
    assert payload["categories"]["x_accounts"]["count"] == 0


@pytest.mark.asyncio
async def test_digest_item_includes_body_preview_when_summary_short(client, db_session):
    source = Source(name="Feed", type=SourceType.RSS, url="https://example.com/feed.xml")
    now = utcnow_naive()
    long_plain = "这是一段用于测试正文预览的重复文字。" * 8
    content = Content(
        source=source,
        title="仅标题",
        summary=None,
        full_content=f"<p>{long_plain}</p>",
        original_url="https://example.com/article",
        content_type="rss",
        fetched_at=now,
        publish_time=now,
        read_status=False,
    )
    db_session.add_all([source, content])
    await db_session.commit()

    response = await client.get(
        "/api/digest",
        params=[("date", _digest_date_param(now)), ("unread_only", "false")],
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["categories"]["rss"]["count"] == 1
    item = payload["categories"]["rss"]["items"][0]
    assert item.get("body_preview")
    assert "用于测试正文预览" in item["body_preview"]
    assert item["body_preview"].endswith("…") or len(item["body_preview"]) <= 300


@pytest.mark.asyncio
async def test_digest_item_uses_summary_when_full_content_short(client, db_session):
    source = Source(name="Feed", type=SourceType.RSS, url="https://example.com/feed.xml")
    now = utcnow_naive()
    summary_plain = "这是 RSS 条目自带的摘要文字，用于在列表中展示预览。"  # >12 chars
    content = Content(
        source=source,
        title="文章标题",
        summary=summary_plain,
        full_content="<p>短</p>",
        original_url="https://example.com/p/1",
        content_type="rss",
        fetched_at=now,
        publish_time=now,
        read_status=False,
    )
    db_session.add_all([source, content])
    await db_session.commit()

    response = await client.get(
        "/api/digest",
        params=[("date", _digest_date_param(now)), ("unread_only", "false")],
    )
    assert response.status_code == 200
    item = response.json()["categories"]["rss"]["items"][0]
    assert item.get("body_preview")
    assert "摘要文字" in item["body_preview"]


@pytest.mark.asyncio
async def test_daily_digest_orders_items_by_publish_time_not_fetch_batch(client, db_session):
    source = Source(name="Batchy", type=SourceType.WEBSITE, url="https://example.com")
    now = utcnow_naive()
    older_published_later_fetched = Content(
        source=source,
        title="Fetched later but published older",
        summary="Summary",
        original_url="https://example.com/old",
        content_type="website",
        fetched_at=now,
        publish_time=now - timedelta(hours=3),
        read_status=False,
    )
    newer_published_earlier_fetched = Content(
        source=source,
        title="Published newer",
        summary="Summary",
        original_url="https://example.com/new",
        content_type="website",
        fetched_at=now - timedelta(minutes=5),
        publish_time=now - timedelta(hours=1),
        read_status=False,
    )
    db_session.add_all([source, older_published_later_fetched, newer_published_earlier_fetched])
    await db_session.commit()

    response = await client.get(
        "/api/digest",
        params=[("date", _digest_date_param(now)), ("unread_only", "false")],
    )

    assert response.status_code == 200
    items = response.json()["categories"]["websites"]["items"]
    assert [item["title"] for item in items[:2]] == [
        "Published newer",
        "Fetched later but published older",
    ]


@pytest.mark.asyncio
async def test_daily_digest_excludes_archived_items(client, db_session):
    source = Source(name="Feed", type=SourceType.RSS, url="https://example.com/feed.xml")
    now = utcnow_naive()
    visible = Content(
        source=source,
        title="Visible item",
        summary="Summary",
        original_url="https://example.com/visible",
        content_type="rss",
        fetched_at=now,
        publish_time=now,
        read_status=False,
    )
    hidden = Content(
        source=source,
        title="Hidden item",
        summary="Summary",
        original_url="https://example.com/hidden",
        content_type="rss",
        fetched_at=now,
        publish_time=now,
        read_status=False,
        archived=True,
    )
    db_session.add_all([source, visible, hidden])
    await db_session.commit()

    response = await client.get(
        "/api/digest",
        params=[("date", _digest_date_param(now)), ("unread_only", "false")],
    )

    assert response.status_code == 200
    items = response.json()["categories"]["rss"]["items"]
    assert [item["title"] for item in items] == ["Visible item"]


@pytest.mark.asyncio
async def test_daily_digest_supports_date_range_and_score_desc(client, db_session):
    source = Source(name="Scored", type=SourceType.WEBSITE, url="https://example.com")
    base = utcnow_naive().replace(hour=3, minute=0, second=0, microsecond=0)
    day = _digest_calendar_date(base)
    day_start = base.replace(tzinfo=timezone.utc).astimezone(_DIGEST_TZ).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    ).astimezone(timezone.utc).replace(tzinfo=None)
    older_in_range = Content(
        source=source,
        title="Low score",
        summary="Summary",
        original_url="https://example.com/low",
        content_type="website",
        fetched_at=day_start + timedelta(hours=2),
        publish_time=day_start + timedelta(hours=2),
        read_status=False,
        metadata_={"final_score": 20},
    )
    newer_in_range = Content(
        source=source,
        title="High score",
        summary="Summary",
        original_url="https://example.com/high",
        content_type="website",
        fetched_at=day_start + timedelta(days=1, hours=2),
        publish_time=day_start + timedelta(days=1, hours=2),
        read_status=False,
        metadata_={"final_score": 95},
    )
    outside_range = Content(
        source=source,
        title="Outside",
        summary="Summary",
        original_url="https://example.com/outside",
        content_type="website",
        fetched_at=day_start + timedelta(days=3, hours=2),
        publish_time=day_start + timedelta(days=3, hours=2),
        read_status=False,
        metadata_={"final_score": 100},
    )
    db_session.add_all([source, older_in_range, newer_in_range, outside_range])
    await db_session.commit()

    response = await client.get(
        "/api/digest",
        params={
            "date_from": day.isoformat(),
            "date_to": (day + timedelta(days=1)).isoformat(),
            "sort": "score_desc",
            "unread_only": "false",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["date"] == f"{day.isoformat()}..{(day + timedelta(days=1)).isoformat()}"
    items = payload["categories"]["websites"]["items"]
    assert [item["title"] for item in items] == ["High score", "Low score"]


@pytest.mark.asyncio
async def test_hourly_digest_endpoints_return_summary_and_detail(client, db_session):
    source = Source(name="Hourly", type=SourceType.WEBSITE, url="https://example.com")
    now = utcnow_naive().replace(minute=10, second=0, microsecond=0)
    cal = _digest_calendar_date(now)
    start_utc, _ = _completed_hour_label_to_utc_window(cal, now.hour)
    digest = HourlyDigest(
        digest_date=cal,
        hour=now.hour,
        title="10 时简报",
        summary="Summary body",
        content_count=1,
        sources=["Hourly"],
        items_json=[
            {
                "content_id": str(uuid4()),
                "title": "Structured event",
                "summary": "Why this matters",
                "source_name": "Hourly",
                "source_url": "https://example.com",
                "url": "https://example.com/hourly",
                "publish_time": None,
                "fetched_at": None,
                "score": 88,
                "lane": "track",
                "duplicate_group_id": "title:abc",
            }
        ],
    )
    content = Content(
        source=source,
        title="Hourly item",
        summary="Summary",
        original_url="https://example.com/hourly",
        content_type="website",
        fetched_at=start_utc,
        publish_time=start_utc,
    )
    db_session.add_all([source, digest, content])
    await db_session.commit()

    hourly_list = await client.get("/api/digest/hourly", params={"date": _digest_date_param(now)})
    assert hourly_list.status_code == 200
    assert hourly_list.json()[0]["title"] == "10 时简报"

    hourly_detail = await client.get(
        f"/api/digest/hourly/{now.hour}", params={"date": _digest_date_param(now)}
    )
    assert hourly_detail.status_code == 200
    assert hourly_detail.json()["summary"] == "Summary body"
    assert hourly_detail.json()["event_items"][0]["title"] == "Structured event"
    assert hourly_detail.json()["event_items"][0]["score"] == 88
    assert hourly_detail.json()["items"][0]["title"] == "Hourly item"


@pytest.mark.asyncio
async def test_hourly_digest_detail_returns_score_top_20_across_types(client, db_session):
    sources = {
        "website": Source(name="Web", type=SourceType.WEBSITE, url="https://example.com"),
        "rss": Source(name="RSS", type=SourceType.RSS, url="https://example.com/feed.xml"),
        "x": Source(name="X", type=SourceType.X, url="https://x.com/example"),
        "youtube": Source(name="YT", type=SourceType.YOUTUBE, url="https://youtube.com/@example"),
        "podcast": Source(name="Podcast", type=SourceType.PODCAST, url="https://example.com/podcast"),
    }
    now = utcnow_naive().replace(minute=10, second=0, microsecond=0)
    cal = _digest_calendar_date(now)
    start_utc, _ = _completed_hour_label_to_utc_window(cal, now.hour, window_hours=1)
    digest = HourlyDigest(
        digest_date=cal,
        hour=now.hour,
        title="Top20 简报",
        summary="Summary body",
        content_count=20,
        sources=[source.name for source in sources.values()],
    )
    db_session.add_all([*sources.values(), digest])

    type_order = list(sources.keys())
    for score in range(1, 23):
        content_type = type_order[score % len(type_order)]
        db_session.add(
            Content(
                source=sources[content_type],
                title=f"Score {score:02d}",
                summary="Summary",
                original_url=f"https://example.com/{score}",
                content_type=content_type,
                fetched_at=start_utc + timedelta(minutes=score),
                publish_time=start_utc + timedelta(minutes=score),
                metadata_={"final_score": score},
            )
        )
    await db_session.commit()

    response = await client.get(
        f"/api/digest/hourly/{now.hour}", params={"date": _digest_date_param(now)}
    )

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 20
    assert [item["title"] for item in items[:3]] == ["Score 22", "Score 21", "Score 20"]
    assert [item["title"] for item in items[-2:]] == ["Score 04", "Score 03"]
    assert "Score 02" not in {item["title"] for item in items}
    assert any(item["source_name"] == "Podcast" for item in items)


def test_completed_hour_label_window_uses_previous_local_hour():
    target_date = date(2026, 3, 31)
    start_utc, end_utc = _completed_hour_label_to_utc_window(target_date, 19)

    assert start_utc.isoformat(sep=" ") == "2026-03-31 10:00:00"
    assert end_utc.isoformat(sep=" ") == "2026-03-31 11:00:00"
