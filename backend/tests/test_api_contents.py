from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.domains.events.repository import stable_event_id
from app.models import Content, ContentEvent, ContentEventMembership, EventMembershipV1, InteractionEvent, PersonalItemState, Source
from app.models.source import SourceType
from app.utils.datetime import utcnow_naive


async def _seed_content(
    db_session,
    *,
    source_name: str = "Example",
    source_url: str = "https://example.com/article",
    title: str = "Example Article",
    metadata: dict | None = None,
    fetched_at=None,
):
    source = Source(name=source_name, type=SourceType.WEBSITE, url="https://example.com")
    now = utcnow_naive()
    content = Content(
        source=source,
        title=title,
        summary="A short summary",
        original_url=source_url,
        full_content="This is a long enough body for reader testing.",
        content_type="website",
        publish_time=now,
        fetched_at=fetched_at or now,
        metadata_=metadata or {},
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

    favorite_off = await client.patch(
        f"/api/contents/{content.id}/favorite",
        json={"favorited": False},
    )
    assert favorite_off.status_code == 200
    assert favorite_off.json()["favorited"] is False

    mark_read = await client.post(f"/api/contents/{content.id}/read")
    assert mark_read.status_code == 200

    personal_state = await db_session.scalar(
        select(PersonalItemState).where(
            PersonalItemState.target_type == "report",
            PersonalItemState.target_id == str(content.id),
        )
    )
    assert personal_state is not None
    assert personal_state.saved is False
    assert personal_state.hidden is True
    assert personal_state.last_seen_version == 1
    interaction_rows = (
        await db_session.execute(
            select(InteractionEvent).where(InteractionEvent.target_id == str(content.id))
        )
    ).scalars().all()
    assert {row.action for row in interaction_rows} >= {"completed", "saved", "hidden"}

    delete_response = await client.delete(f"/api/contents/{content.id}")
    assert delete_response.status_code == 200

    final_list = await client.get("/api/contents")
    assert final_list.status_code == 200
    assert final_list.json()["total"] == 0


@pytest.mark.asyncio
async def test_formal_content_actions_and_tags_feed_annotations(client, db_session, monkeypatch):
    monkeypatch.setenv("PIM_RUNTIME_PROFILE", "development")
    _, content = await _seed_content(
        db_session,
        metadata={"lane": "company_news"},
    )

    important = await client.patch(
        f"/api/contents/{content.id}/favorite",
        json={"favorited": True},
    )
    assert important.status_code == 200
    target = await client.get(f"/api/annotations/targets/content/{content.id}")
    value_task = next(item for item in target.json()["items"] if item["task_type"] == "content_value")
    assert value_task["latest_label"]["label_payload"] == {"value": "must_see"}

    unimportant = await client.patch(
        f"/api/contents/{content.id}",
        json={"archived": True},
    )
    assert unimportant.status_code == 200
    target = await client.get(f"/api/annotations/targets/content/{content.id}")
    value_task = next(item for item in target.json()["items"] if item["task_type"] == "content_value")
    assert value_task["latest_label"]["label_payload"] == {"value": "noise"}

    tags = await client.patch(
        f"/api/contents/{content.id}/tags",
        json={"tags": ["macro_finance", "markets"]},
    )
    assert tags.status_code == 200
    assert tags.json()["tags"] == ["macro_finance", "markets"]

    reader = await client.get(f"/api/contents/{content.id}/reader")
    assert reader.status_code == 200
    assert reader.json()["tags"] == ["macro_finance", "markets"]
    assert reader.json()["lane"] == "macro_finance"

    target = await client.get(f"/api/annotations/targets/content/{content.id}")
    tag_task = next(item for item in target.json()["items"] if item["task_type"] == "content_tags")
    assert tag_task["latest_label"]["label_payload"] == {
        "values": ["macro_finance", "markets"],
    }


@pytest.mark.asyncio
async def test_contents_list_filters_by_source_id(client, db_session):
    source_a, content_a = await _seed_content(db_session, source_name="36kr", title="First article")
    await _seed_content(db_session, source_name="TechCrunch", title="Second article")

    response = await client.get("/api/contents", params={"source_id": str(source_a.id)})

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == str(content_a.id)
    assert payload["items"][0]["source_name"] == "36kr"


@pytest.mark.asyncio
async def test_contents_list_collapses_legacy_duplicate_group(client, db_session):
    earlier = utcnow_naive() - timedelta(minutes=2)
    later = utcnow_naive() - timedelta(minutes=1)
    _, canonical = await _seed_content(
        db_session,
        title="Same article title",
        source_url="https://example.com/a",
        metadata={"duplicate_group_id": "title:same"},
        fetched_at=earlier,
    )
    await _seed_content(
        db_session,
        title="Same article title",
        source_url="https://example.com/b",
        metadata={"duplicate_group_id": "title:same"},
        fetched_at=later,
    )

    response = await client.get("/api/contents")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == str(canonical.id)


@pytest.mark.asyncio
async def test_contents_list_uses_explicit_canonical_when_later_row_is_better(client, db_session):
    earlier = utcnow_naive() - timedelta(minutes=2)
    later = utcnow_naive() - timedelta(minutes=1)
    _, duplicate = await _seed_content(
        db_session,
        title="Same article title",
        source_url="https://example.com/summary",
        metadata={"duplicate_group_id": "title:quality", "is_duplicate": True},
        fetched_at=earlier,
    )
    _, canonical = await _seed_content(
        db_session,
        title="Same article title",
        source_url="https://example.com/full",
        metadata={"duplicate_group_id": "title:quality", "is_duplicate": False},
        fetched_at=later,
    )
    duplicate.is_duplicate = True
    duplicate.duplicate_of = str(canonical.id)
    await db_session.commit()

    response = await client.get("/api/contents")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == str(canonical.id)


@pytest.mark.asyncio
async def test_contents_list_excludes_archived_by_default(client, db_session):
    _, visible = await _seed_content(db_session, title="Visible article")
    _, hidden = await _seed_content(db_session, title="Hidden article")
    hidden.archived = True
    await db_session.commit()

    response = await client.get("/api/contents")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == str(visible.id)

    archived_response = await client.get("/api/contents", params={"archived": "true"})
    assert archived_response.status_code == 200
    archived_payload = archived_response.json()
    assert archived_payload["total"] == 1
    assert archived_payload["items"][0]["id"] == str(hidden.id)


@pytest.mark.asyncio
async def test_contents_search_matches_source_name(client, db_session):
    _, content = await _seed_content(db_session, source_name="Product Hunt", title="Unrelated launch")
    await _seed_content(db_session, source_name="Other Source", title="Another item")

    response = await client.get("/api/contents", params={"search": "Product Hunt"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == str(content.id)


@pytest.mark.asyncio
async def test_reader_payload_includes_source_id(client, db_session):
    source, content = await _seed_content(db_session, source_name="36kr")

    response = await client.get(f"/api/contents/{content.id}/reader")

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_id"] == str(source.id)
    assert payload["source_name"] == "36kr"
    assert payload["blocks"][0] == {
        "type": "paragraph",
        "text": "This is a long enough body for reader testing.",
    }


@pytest.mark.asyncio
async def test_export_single_content_markdown_omits_full_body_by_default(client, db_session):
    _, content = await _seed_content(
        db_session,
        source_name="Paid Source",
        source_url="https://example.com/paid-story",
        title="Paid Story",
        metadata={"duplicate_group_id": "event:paid-story"},
    )
    content.full_content = "Subscriber-only body should not be redistributed."
    await db_session.commit()

    response = await client.get(f"/api/contents/{content.id}/export-md")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    markdown = response.text
    assert "# Paid Story" in markdown
    assert "来源：Paid Source" in markdown
    assert f"PIM 内容 ID：{content.id}" in markdown
    assert "PIM 链接：pim://content/" in markdown
    assert "原文链接：https://example.com/paid-story" in markdown
    assert "近重复组：event:paid-story" in markdown
    assert "Subscriber-only body should not be redistributed" not in markdown
    assert "默认导出不包含完整正文" in markdown


@pytest.mark.asyncio
async def test_export_event_markdown_contains_timeline_without_full_body(client, db_session):
    _, first = await _seed_content(
        db_session,
        source_name="Source A",
        source_url="https://example.com/a",
        title="Event Story A",
        metadata={"duplicate_group_id": "event:launch"},
    )
    _, second = await _seed_content(
        db_session,
        source_name="Source B",
        source_url="https://example.com/b",
        title="Event Story B",
        metadata={"duplicate_group_id": "event:launch"},
    )
    first.full_content = "Paid body A"
    second.full_content = "Paid body B"
    event_key = "event:launch"
    event_id = stable_event_id(event_key)
    db_session.add(
        ContentEvent(
            event_id=event_id,
            event_key=event_key,
            title="Event Story",
            summary="Event summary",
            source_names=["Source A", "Source B"],
        )
    )
    db_session.add_all(
        [
            ContentEventMembership(event_id=event_id, content_id=str(first.id), role="primary"),
            ContentEventMembership(event_id=event_id, content_id=str(second.id), role="supporting"),
        ]
    )
    await db_session.commit()

    response = await client.get("/api/contents/events/export-md", params={"event_key": "event:launch"})

    assert response.status_code == 200
    markdown = response.text
    assert "# Event Story" in markdown
    assert "事件键：event:launch" in markdown
    assert "报道数：2" in markdown
    assert "Source A" in markdown
    assert "Source B" in markdown
    assert f"pim://content/{first.id}" in markdown
    assert "https://example.com/b" in markdown
    assert "Paid body A" not in markdown
    assert "Event 导出默认只包含标题" in markdown


@pytest.mark.asyncio
async def test_export_event_markdown_supports_v1_membership(client, db_session):
    _, content = await _seed_content(
        db_session,
        source_name="V1 Source",
        source_url="https://example.com/v1",
        title="V1 Event Story",
    )
    event_key = "event:v1-export"
    event_id = stable_event_id(event_key)
    db_session.add(
        ContentEvent(
            event_id=event_id,
            event_key=event_key,
            title="V1 Event",
            summary="V1 summary",
            cluster_version="event-v1",
            source_names=["V1 Source"],
        )
    )
    db_session.add(
        EventMembershipV1(
            event_id=event_id,
            content_id=str(content.id),
            assignment_version="v1-test",
            role="primary",
            shadow_only=False,
            active=True,
        )
    )
    inactive_content = Content(
        source_id=content.source_id,
        external_id="inactive-v1-export",
        title="Inactive superseded report",
        original_url="https://example.com/v1/inactive",
        content_type="article",
    )
    db_session.add(inactive_content)
    await db_session.flush()
    db_session.add(
        EventMembershipV1(
            event_id=event_id,
            content_id=str(inactive_content.id),
            assignment_version="v1-test",
            role="supporting",
            shadow_only=False,
            active=False,
        )
    )
    await db_session.commit()

    response = await client.get("/api/contents/events/export-md", params={"event_key": event_key})

    assert response.status_code == 200
    assert "V1 Event Story" in response.text
    assert "Inactive superseded report" not in response.text
    assert f"pim://content/{content.id}" in response.text


@pytest.mark.asyncio
async def test_export_single_content_markdown_404(client):
    response = await client.get("/api/contents/00000000-0000-0000-0000-000000000000/export-md")

    assert response.status_code == 404


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
async def test_contents_cleanup_junk_dry_run_and_apply(client, db_session):
    source = Source(name="36kr-test", type=SourceType.RSS, url="https://36kr.com/feed")
    now = utcnow_naive()
    png_body = (b"\x89PNG\r\n\x1a\n" + b"0" * 80).decode("latin-1")
    junk_binary = Content(
        source=source,
        title="36碳",
        summary=png_body,
        full_content="",
        original_url="https://36kr.com/carbon",
        content_type="rss",
        publish_time=now,
        fetched_at=now,
    )
    junk_thin = Content(
        source=source,
        title="36氪出海",
        summary="",
        full_content="",
        original_url="https://36kr.com/chuhai",
        content_type="rss",
        publish_time=now,
        fetched_at=now,
    )
    keep = Content(
        source=source,
        title="正常文章标题示例",
        summary="这是一条足够长度的 RSS 摘要文字，用于保留在库中不被误删。",
        full_content="",
        original_url="https://36kr.com/p/123456",
        content_type="rss",
        publish_time=now,
        fetched_at=now,
    )
    db_session.add_all([source, junk_binary, junk_thin, keep])
    await db_session.commit()

    dry = await client.post("/api/contents/cleanup-junk")
    assert dry.status_code == 200
    data = dry.json()
    assert data["matched_count"] == 2
    assert data["by_reason"]["embedded_binary"] == 1
    assert data["by_reason"]["rss_thin_or_empty_text"] == 1

    applied = await client.post("/api/contents/cleanup-junk", params={"apply": "true"})
    assert applied.status_code == 200
    assert applied.json()["deleted_count"] == 2

    remaining = await client.get("/api/contents")
    assert remaining.status_code == 200
    assert remaining.json()["total"] == 1
    assert remaining.json()["items"][0]["title"] == "正常文章标题示例"


@pytest.mark.asyncio
async def test_contents_page_size_has_explicit_upper_bound(client):
    response = await client.get("/api/contents", params={"page_size": 201})
    assert response.status_code == 422
