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
from scripts.run_web_clean_shadow import build_web_clean_shadow_report
from app.domains.fetch.web_clean.provenance import sign_shadow_provenance

_TEST_PROVENANCE_KEY = "audit-only-test-key-at-least-32-bytes"


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




def _web_clean_snapshot(day: int, *, reviewed: bool = True) -> dict:
    return {
        "observed_at": f"2026-07-{day:02d}T08:00:00Z",
        "content_id": "content-secret",
        "source_id": "source-secret",
        "old_text_chars": 1000,
        "new_text_chars": 300,
        "old_quality_status": "good",
        "new_quality_status": "poor",
        "production_affected": False,
        "review_verdict": "accepted" if reviewed else None,
        "url": "https://private.example/story",
        "full_content": "must be removed",
        "authorization": "Bearer must-not-leak",
    }


def _production_provenance(input_sha256: str = "observations-sha") -> dict:
    provenance = {
        "schema_version": "pim-web-clean-shadow-export-v1",
        "generated_by": "pim-production-shadow-export",
        "dataset_kind": "production_shadow",
        "observations_sha256": input_sha256,
        "generated_at": "2026-07-29T00:00:00Z",
    }
    provenance["attestation_hmac_sha256"] = sign_shadow_provenance(
        provenance,
        key=_TEST_PROVENANCE_KEY,
    )
    return provenance


def test_web_clean_shadow_report_is_provenance_bounded_and_sanitized():
    report = build_web_clean_shadow_report(
        [_web_clean_snapshot(day) for day in range(1, 8)],
        salt="run-1",
        dataset_kind="local_fixture",
    )

    assert report["dataset_kind"] == "local_fixture"
    assert report["shadow_only"] is True
    assert report["production_affected"] is False
    assert report["window"]["minimum_days_met"] is True
    assert report["window"]["consecutive_days"] == 7
    assert report["release_eligible"] is False
    sample = report["high_risk_review"]["samples"][0]
    assert sample["content_id"] != "content-secret"
    assert sample["source_id"] != "source-secret"
    assert "url" not in sample
    assert "full_content" not in sample
    assert "authorization" not in sample

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

    web_clean = {
        "version": "web-clean-eval-v2",
        "ok": True,
        "gate": {"result": "GO", "blockers": []},
        "dataset_tier": "web_clean_eval_1_0",
        "manifest_valid": True,
        "dataset_sha256": "web-clean",
        "manifest_sha256": "web-clean-manifest",
        "metrics": {
            "sample_count": 150,
            "must_include_recall": 0.91,
            "must_exclude_precision": 0.93,
            "boilerplate_leak_rate": 0.07,
            "blocked_detection_f1": 0.89,
            "metadata_accuracy": 0.91,
            "markdown_structure_score": 0.86,
            "runtime_p95_ms": 10.0,
            "label_counts": {
                "must_include": 1,
                "must_exclude": 1,
                "title": 1,
                "canonical_url": 1,
                "published_time": 1,
                "quality_status": 1,
                "markdown": 1,
            },
        },
    }
    web_clean_shadow = build_web_clean_shadow_report(
        [_web_clean_snapshot(day) for day in range(1, 8)],
        salt="run-1",
        dataset_kind="production_shadow",
        provenance=_production_provenance(),
        input_sha256="observations-sha",
        provenance_hmac_key=_TEST_PROVENANCE_KEY,
    )

    artifact = build_release_artifact(
        formal,
        shadow,
        config_path=config,
        lock_path=lock,
        performance={"candidate_pool_p95_ms": 20},
        web_clean=web_clean,
        web_clean_shadow=web_clean_shadow,
        approvers=["owner"],
        commit="abc123",
        web_clean_provenance_hmac_key=_TEST_PROVENANCE_KEY,
    )

    assert artifact["decision"] == {"result": "GO", "blockers": [], "approvers": ["owner"]}


def test_release_artifact_rejects_forged_web_clean_ok_without_v2_gate_or_labels(tmp_path):
    config = tmp_path / "config.json"
    lock = tmp_path / "lock"
    config.write_text("{}", encoding="utf-8")
    lock.write_text("locked", encoding="utf-8")
    report = {
        "ok": True,
        "dataset_tier": "web_clean_eval_1_0",
        "manifest_valid": True,
        "dataset_sha256": "dataset",
        "manifest_sha256": "manifest",
        "metrics": {"sample_count": 150},
    }

    artifact = build_release_artifact(
        None,
        None,
        config_path=config,
        lock_path=lock,
        performance=None,
        web_clean=report,
        web_clean_shadow=None,
        approvers=[],
        commit="abc123",
    )

    blockers = artifact["decision"]["blockers"]
    assert "Web Clean report version is not web-clean-eval-v2" in blockers
    assert "Web Clean report gate is not GO" in blockers
    assert "Web Clean Eval has no must_include labels" in blockers
    assert "Web Clean runtime_p95_ms is missing or invalid" in blockers


def test_web_clean_shadow_requires_continuous_days_all_reviews_and_isolation():
    non_contiguous = [_web_clean_snapshot(day) for day in (1, 2, 3, 10, 11, 12, 13)]
    report = build_web_clean_shadow_report(
        non_contiguous,
        salt="run-1",
        dataset_kind="production_shadow",
        provenance=_production_provenance(),
        input_sha256="observations-sha",
    )
    assert report["window"]["observed_days"] == 7
    assert report["window"]["consecutive_days"] == 4
    assert report["release_eligible"] is False

    many = [_web_clean_snapshot((index % 7) + 1, reviewed=index != 55) for index in range(60)]
    report = build_web_clean_shadow_report(
        many,
        salt="run-1",
        dataset_kind="production_shadow",
        high_risk_limit=10,
        provenance=_production_provenance(),
        input_sha256="observations-sha",
    )
    assert report["high_risk_review"]["total_count"] == 60
    assert report["high_risk_review"]["sample_count"] == 10
    assert report["high_risk_review"]["reviewed_count"] == 59
    assert report["release_eligible"] is False

    violated = [_web_clean_snapshot(day) for day in range(1, 8)]
    violated[0]["production_affected"] = True
    report = build_web_clean_shadow_report(
        violated,
        salt="run-1",
        dataset_kind="production_shadow",
        provenance=_production_provenance(),
        input_sha256="observations-sha",
    )
    assert report["shadow_only"] is False
    assert report["production_affected"] is True
    assert report["observations"]["shadow_isolation_violations"] == 1
    assert report["release_eligible"] is False


def test_production_shadow_label_without_export_provenance_cannot_pass():
    report = build_web_clean_shadow_report(
        [_web_clean_snapshot(day) for day in range(1, 8)],
        salt="run-1",
        dataset_kind="production_shadow",
    )

    assert report["provenance"]["valid"] is False
    assert report["release_eligible"] is False


def test_web_clean_shadow_never_retains_unsampled_sensitive_rows():
    observations = [_web_clean_snapshot((index % 7) + 1) for index in range(60)]
    observations[-1]["full_content"] = "last-row-secret"
    observations[-1]["quality_score"] = float("nan")

    report = build_web_clean_shadow_report(
        observations,
        salt="run-1",
        dataset_kind="local_fixture",
        high_risk_limit=2,
    )

    assert report["high_risk_review"]["total_count"] == 60
    assert report["high_risk_review"]["sample_count"] == 2
    assert "last-row-secret" not in json.dumps(report)
    assert "NaN" not in json.dumps(report)
