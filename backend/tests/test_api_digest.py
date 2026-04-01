from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from app.api.digest import _completed_hour_label_to_utc_window
from app.models import Content, HourlyDigest, Source
from app.models.source import SourceType
from app.utils.datetime import utcnow_naive


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
                ("date", now.date().isoformat()),
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
async def test_hourly_digest_endpoints_return_summary_and_detail(client, db_session):
    source = Source(name="Hourly", type=SourceType.WEBSITE, url="https://example.com")
    now = utcnow_naive().replace(minute=10, second=0, microsecond=0)
    start_utc, _ = _completed_hour_label_to_utc_window(now.date(), now.hour)
    digest = HourlyDigest(
        digest_date=now.date(),
        hour=now.hour,
        title="10 时简报",
        summary="Summary body",
        content_count=1,
        sources=["Hourly"],
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

    hourly_list = await client.get("/api/digest/hourly", params={"date": now.date().isoformat()})
    assert hourly_list.status_code == 200
    assert hourly_list.json()[0]["title"] == "10 时简报"

    hourly_detail = await client.get(f"/api/digest/hourly/{now.hour}", params={"date": now.date().isoformat()})
    assert hourly_detail.status_code == 200
    assert hourly_detail.json()["summary"] == "Summary body"
    assert hourly_detail.json()["items"][0]["title"] == "Hourly item"


def test_completed_hour_label_window_uses_previous_local_hour():
    target_date = date(2026, 3, 31)
    start_utc, end_utc = _completed_hour_label_to_utc_window(target_date, 19)

    assert start_utc.isoformat(sep=" ") == "2026-03-31 10:00:00"
    assert end_utc.isoformat(sep=" ") == "2026-03-31 11:00:00"
