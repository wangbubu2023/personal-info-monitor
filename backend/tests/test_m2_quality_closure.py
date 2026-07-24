from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.domains.score.feedback import record_score_feedback_event
from app.models import Content, Source
from app.models.source import SourceType
from scripts.generate_release_eval_artifact import build_release_artifact
from scripts.run_quality_shadow import build_shadow_report, prune_expired_shadow_reports


@pytest.mark.asyncio
async def test_quality_feedback_requires_adjudication_before_gold_candidate(client, db_session):
    source = Source(name="Official", type=SourceType.WEBSITE, url="https://official.example")
    content = Content(
        source=source,
        title="Reported event",
        original_url="https://official.example/story",
        content_type="website",
        fetched_at=datetime(2026, 7, 24, 8, 0),
    )
    db_session.add_all([source, content])
    await db_session.commit()

    observed = await client.post(
        "/api/events/event-1/feedback",
        json={"type": "event_wrong_title", "content_id": str(content.id), "note": "title overstates the fact"},
    )
    assert observed.status_code == 200

    queue = await client.get("/api/events/quality-feedback/queue")
    assert queue.status_code == 200
    observation = queue.json()[0]
    assert observation["status"] == "observation"
    assert observation["gold_candidate"] is False

    decided = await client.post(
        f"/api/events/quality-feedback/{observation['feedback_id']}/adjudicate",
        json={
            "verdict": "confirmed",
            "adjudicator": "reviewer-a",
            "rationale": "The source only announced a plan.",
            "evidence": {"policy_version": "event-label-v1"},
        },
    )
    assert decided.status_code == 200
    assert decided.json()["gold_candidate"] is True
    assert decided.json()["hard_negative"] is False

    adjudicated = await client.get("/api/events/quality-feedback/queue", params={"status": "adjudicated"})
    assert adjudicated.status_code == 200
    assert adjudicated.json()[0]["verdict"] == "confirmed"

    duplicate = await client.post(
        f"/api/events/quality-feedback/{observation['feedback_id']}/adjudicate",
        json={"verdict": "rejected", "adjudicator": "reviewer-b", "rationale": "second opinion"},
    )
    assert duplicate.status_code == 409


@pytest.mark.asyncio
async def test_natural_reading_feedback_is_excluded_from_quality_queue(client, db_session):
    source = Source(name="Reader", type=SourceType.WEBSITE, url="https://reader.example")
    content = Content(
        source=source,
        title="Read item",
        original_url="https://reader.example/story",
        content_type="website",
    )
    db_session.add_all([source, content])
    await db_session.flush()
    await record_score_feedback_event(db_session, content, event_type="open")
    await db_session.commit()

    queue = await client.get("/api/events/quality-feedback/queue", params={"status": "all"})

    assert queue.status_code == 200
    assert queue.json() == []


def _snapshot(day: int) -> dict:
    return {
        "observed_at": f"2026-07-{day:02d}T08:00:00Z",
        "score_diffs": [{"content_id": "content-secret", "old_score": 60, "new_score": 70, "title": "removed"}],
        "event_diffs": [
            {
                "content_id": "content-secret",
                "old_event_id": "event-a",
                "new_event_id": "event-b",
                "risk": "high",
                "review_verdict": "wrong_merge",
                "full_content": "removed",
            }
        ],
        "today_diffs": [{"content_id": "content-secret", "old_rank": 1, "new_rank": 2, "risk": "high"}],
    }


def test_shadow_report_is_isolated_retained_and_sanitized():
    report = build_shadow_report([_snapshot(day) for day in range(1, 8)], salt="run-1")

    assert report["shadow_only"] is True
    assert report["production_affected"] is False
    assert report["window"]["minimum_days_met"] is True
    assert report["window"]["recommended_days_met"] is False
    assert report["event"]["id_churn"] == 1.0
    sample = report["high_risk_review"]["samples"][0]
    assert sample["content_id"] != "content-secret"
    assert "full_content" not in sample
    assert "title" not in sample


def test_shadow_retention_prunes_only_expired_json(tmp_path):
    expired = tmp_path / "expired.json"
    future = tmp_path / "future.json"
    ignored = tmp_path / "notes.txt"
    expired.write_text(json.dumps({"retention": {"delete_after": "2026-07-01T00:00:00Z"}}), encoding="utf-8")
    future.write_text(json.dumps({"retention": {"delete_after": "2026-08-01T00:00:00Z"}}), encoding="utf-8")
    ignored.write_text("keep", encoding="utf-8")

    removed = prune_expired_shadow_reports(tmp_path, now=datetime(2026, 7, 24, tzinfo=timezone.utc))

    assert removed == ["expired.json"]
    assert not expired.exists()
    assert future.exists()
    assert ignored.exists()


def test_release_artifact_fails_closed_without_real_eval_and_shadow(tmp_path):
    config = tmp_path / "config.json"
    lock = tmp_path / "lock"
    config.write_text("{}", encoding="utf-8")
    lock.write_text("locked", encoding="utf-8")

    artifact = build_release_artifact(
        None,
        None,
        config_path=config,
        lock_path=lock,
        performance=None,
        approvers=[],
        commit="abc123",
    )

    assert artifact["decision"]["result"] == "NO_GO"
    assert "formal Core/Event Eval 1.0 is missing or failed" in artifact["decision"]["blockers"]
    assert artifact["provenance"]["config_sha256"]


def test_release_artifact_go_requires_every_gate(tmp_path):
    config = tmp_path / "config.json"
    lock = tmp_path / "lock"
    config.write_text("{}", encoding="utf-8")
    lock.write_text("locked", encoding="utf-8")
    formal = {
        "ok": True,
        "dataset_tier": "formal_eval_1_0",
        "production_diff": {},
        "core": {"record_count": 200, "dataset_sha256": "core", "metrics": {"ranking": {}, "calibration": {}}},
        "event": {
            "pair_count": 200,
            "dataset_sha256": "event",
            "metrics": {
                "pairwise": {"precision": 0.93, "recall": 0.84},
                "wrong_merge_rate": 0.02,
                "missing_merge_rate": 0.07,
            },
        },
    }
    shadow = {
        "shadow_only": True,
        "production_affected": False,
        "window": {"minimum_days_met": True, "observed_days": 7},
        "high_risk_review": {"sample_count": 2, "reviewed_count": 2},
    }

    artifact = build_release_artifact(
        formal,
        shadow,
        config_path=config,
        lock_path=lock,
        performance={"candidate_pool_p95_ms": 20},
        approvers=["owner"],
        commit="abc123",
    )

    assert artifact["decision"] == {"result": "GO", "blockers": [], "approvers": ["owner"]}
