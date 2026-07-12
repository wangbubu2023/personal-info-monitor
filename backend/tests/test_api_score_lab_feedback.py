from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Content, Source
from app.models.score_feedback import ScoreFeedback
from app.models.source import SourceType
from app.utils.datetime import utcnow_naive


async def _seed_scored_content(db_session):
    source = Source(
        name="Score Source",
        type=SourceType.WEBSITE,
        url="https://score.example.com",
        metadata_={"source_stars": 3},
    )
    content = Content(
        source=source,
        title="OpenAI releases a major model update",
        summary="The company announced new capabilities.",
        original_url="https://score.example.com/model",
        full_content="OpenAI released a major model update. " * 20,
        content_type="website",
        publish_time=utcnow_naive(),
        fetched_at=utcnow_naive(),
        metadata_={"article_score": 72.0, "selection_status": "selected", "lane": "tech_product"},
    )
    db_session.add_all([source, content])
    await db_session.commit()
    await db_session.refresh(content)
    return content


@pytest.mark.asyncio
async def test_score_lab_feedback_records_calibration_event(client, db_session):
    content = await _seed_scored_content(db_session)

    response = await client.post(
        "/api/score-lab/feedback",
        json={
            "content_id": str(content.id),
            "direction": "too_high",
            "expected_status": "candidate",
            "note": "Too promotional",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["direction"] == "too_high"
    assert payload["event_type"] == "score_calibration"
    assert payload["event_value"] == "too_high"
    assert payload["expected_status"] == "candidate"
    assert payload["snapshot"]["stored_article_score"] == 72.0

    rows = (
        await db_session.execute(
            select(ScoreFeedback).where(ScoreFeedback.content_id == str(content.id))
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].event_type == "score_calibration"
    assert rows[0].event_value == "too_high"


@pytest.mark.asyncio
async def test_score_lab_contents_filters_use_score_columns(client, db_session):
    source = Source(
        name="Column Score Source",
        type=SourceType.WEBSITE,
        url="https://column-score.example.com",
    )
    content = Content(
        source=source,
        title="Column-only scored item",
        summary="No score metadata needed.",
        original_url="https://column-score.example.com/story",
        full_content="Body " * 80,
        content_type="website",
        publish_time=utcnow_naive(),
        fetched_at=utcnow_naive(),
        metadata_={},
        article_score=83.0,
        final_score=83.0,
        selection_status="selected",
        lane="tech_product",
    )
    db_session.add_all([source, content])
    await db_session.commit()

    response = await client.get(
        "/api/score-lab/contents",
        params={"selection_status": "selected", "lane": "tech_product", "min_score": 80},
    )

    assert response.status_code == 200
    items = response.json()["items"]
    assert any(item["id"] == str(content.id) for item in items)
    item = next(item for item in items if item["id"] == str(content.id))
    assert item["article_score"] == 83.0
    assert item["selection_status"] == "selected"
    assert item["lane"] == "tech_product"


@pytest.mark.asyncio
async def test_score_lab_feedback_list_includes_interaction_events(client, db_session):
    content = await _seed_scored_content(db_session)

    reader = await client.get(f"/api/contents/{content.id}/reader")
    assert reader.status_code == 200
    favorite = await client.patch(f"/api/contents/{content.id}/favorite", json={"favorited": True})
    assert favorite.status_code == 200
    archive = await client.patch(f"/api/contents/{content.id}", json={"archived": True})
    assert archive.status_code == 200

    response = await client.get("/api/score-lab/feedback")

    assert response.status_code == 200
    items = response.json()["items"]
    event_types = {item["event_type"] for item in items}
    assert {"opened", "saved", "hidden"} <= event_types
    values = {item["event_type"]: item["event_value"] for item in items}
    assert values["saved"] is True
    assert values["hidden"] is True
