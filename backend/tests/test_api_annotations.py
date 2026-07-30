"""Development-profile annotation API tests."""

from __future__ import annotations

import pytest


def _label(value: str, *, independent: bool = False) -> dict:
    return {
        "task_type": "content_quality",
        "target_type": "content",
        "target_id": "content-annotation-1",
        "label_payload": {"value": value},
        "context_snapshot": {"title": "A useful article"},
        "independent": independent,
    }


@pytest.mark.asyncio
async def test_annotations_fail_closed_outside_development(client, monkeypatch):
    monkeypatch.setenv("PIM_RUNTIME_PROFILE", "production")
    response = await client.post("/api/annotations/labels", json=_label("high"))
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_inline_label_is_append_only_and_queryable(client, monkeypatch):
    monkeypatch.setenv("PIM_RUNTIME_PROFILE", "development")

    first = await client.post("/api/annotations/labels", json=_label("high"))
    assert first.status_code == 200
    assert first.json()["task_status"] == "labeled"

    duplicate = await client.post("/api/annotations/labels", json=_label("high"))
    assert duplicate.status_code == 200
    assert duplicate.json()["id"] == first.json()["id"]

    corrected = await client.post("/api/annotations/labels", json=_label("medium"))
    assert corrected.status_code == 200
    assert corrected.json()["supersedes_id"] == first.json()["id"]

    target = await client.get("/api/annotations/targets/content/content-annotation-1")
    assert target.status_code == 200
    task = target.json()["items"][0]
    assert task["label_count"] == 2
    assert task["latest_label"]["label_payload"] == {"value": "medium"}


@pytest.mark.asyncio
async def test_independent_disagreement_enters_adjudication_queue(client, monkeypatch):
    monkeypatch.setenv("PIM_RUNTIME_PROFILE", "development")
    await client.post("/api/annotations/labels", json=_label("high"))
    conflict = await client.post("/api/annotations/labels", json=_label("low", independent=True))
    assert conflict.status_code == 200
    task_id = conflict.json()["task_id"]
    assert conflict.json()["task_status"] == "needs_adjudication"

    queue = await client.get("/api/annotations/review-queue")
    assert queue.status_code == 200
    assert queue.json()["total"] == 1
    assert queue.json()["items"][0]["id"] == task_id

    adjudicated = await client.post(
        f"/api/annotations/tasks/{task_id}/adjudicate",
        json={
            "final_payload": {"value": "medium"},
            "rationale": "Reviewed the full article and resolved the disagreement.",
        },
    )
    assert adjudicated.status_code == 200
    assert adjudicated.json()["final_payload"] == {"value": "medium"}

    stats = await client.get("/api/annotations/stats")
    assert stats.status_code == 200
    assert stats.json()["adjudicated"] == 1
    assert stats.json()["needs_adjudication"] == 0


@pytest.mark.asyncio
async def test_annotation_vocabulary_is_validated(client, monkeypatch):
    monkeypatch.setenv("PIM_RUNTIME_PROFILE", "development")
    payload = {
        "task_type": "content_lane",
        "target_type": "content",
        "target_id": "content-annotation-2",
        "label_payload": {"value": "made_up_lane"},
    }
    response = await client.post("/api/annotations/labels", json=payload)
    assert response.status_code == 422
