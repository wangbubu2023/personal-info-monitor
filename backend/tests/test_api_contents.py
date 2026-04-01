from __future__ import annotations

import pytest

from app.models import Content, Source
from app.models.source import SourceType
from app.utils.datetime import utcnow_naive


async def _seed_content(db_session, *, source_url: str = "https://example.com/article", title: str = "Example Article"):
    source = Source(name="Example", type=SourceType.WEBSITE, url="https://example.com")
    content = Content(
        source=source,
        title=title,
        summary="A short summary",
        original_url=source_url,
        full_content="This is a long enough body for reader testing.",
        content_type="website",
        publish_time=utcnow_naive(),
        fetched_at=utcnow_naive(),
    )
    db_session.add_all([source, content])
    await db_session.commit()
    await db_session.refresh(content)
    return source, content


@pytest.mark.asyncio
async def test_contents_crud_endpoints(client, db_session):
    _, content = await _seed_content(db_session)

    list_response = await client.get("/api/contents")
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1

    get_response = await client.get(f"/api/contents/{content.id}")
    assert get_response.status_code == 200
    assert get_response.json()["title"] == "Example Article"

    update_response = await client.patch(
        f"/api/contents/{content.id}",
        json={"read_status": True, "favorited": True, "archived": True},
    )
    assert update_response.status_code == 200
    assert update_response.json()["favorited"] is True

    favorite_toggle = await client.post(f"/api/contents/{content.id}/favorite")
    assert favorite_toggle.status_code == 200
    assert favorite_toggle.json()["favorited"] is False

    mark_read = await client.post(f"/api/contents/{content.id}/read")
    assert mark_read.status_code == 200

    delete_response = await client.delete(f"/api/contents/{content.id}")
    assert delete_response.status_code == 200

    final_list = await client.get("/api/contents")
    assert final_list.status_code == 200
    assert final_list.json()["total"] == 0


@pytest.mark.asyncio
async def test_contents_cleanup_low_signal_dry_run_and_apply(client, db_session):
    source = Source(name="HBR", type=SourceType.WEBSITE, url="https://hbr.org")
    junk = Content(
        source=source,
        title="Subscribe",
        summary="",
        original_url="https://hbr.org/subscribe",
        content_type="website",
        publish_time=utcnow_naive(),
        fetched_at=utcnow_naive(),
    )
    article = Content(
        source=source,
        title="How AI Changes Team Strategy",
        summary="Useful summary",
        original_url="https://hbr.org/2026/03/how-ai-changes-team-strategy",
        content_type="website",
        publish_time=utcnow_naive(),
        fetched_at=utcnow_naive(),
    )
    db_session.add_all([source, junk, article])
    await db_session.commit()

    dry_run = await client.post("/api/contents/cleanup-low-signal")
    assert dry_run.status_code == 200
    assert dry_run.json()["matched_count"] == 1
    assert dry_run.json()["preview"][0]["title"] == "Subscribe"

    apply_response = await client.post("/api/contents/cleanup-low-signal", params={"apply": "true"})
    assert apply_response.status_code == 200
    assert apply_response.json()["deleted_count"] == 1

    remaining = await client.get("/api/contents")
    assert remaining.status_code == 200
    assert remaining.json()["total"] == 1
    assert remaining.json()["items"][0]["title"] == "How AI Changes Team Strategy"


@pytest.mark.asyncio
async def test_contents_page_size_has_explicit_upper_bound(client):
    response = await client.get("/api/contents", params={"page_size": 201})
    assert response.status_code == 422
