import hashlib
import json
from pathlib import Path

from scripts.generate_release_eval_artifact import build_release_artifact
from scripts.run_web_clean_shadow import build_web_clean_shadow_report
from app.domains.fetch.web_clean.provenance import sign_shadow_provenance

_TEST_PROVENANCE_KEY = "audit-only-test-key-at-least-32-bytes"


def _observations() -> list[dict]:
    return [
        {
            "observed_at": f"2026-07-{day:02d}T08:00:00Z",
            "content_id": "content-secret",
            "old_text_chars": 1000,
            "new_text_chars": 300,
            "old_quality_status": "good",
            "new_quality_status": "poor",
            "production_affected": False,
            "review_verdict": "accepted",
            "url": "https://user:password@example.test/story?token=secret",
            "full_content": "must not leak",
            "authorization": "Bearer secret",
        }
        for day in range(1, 8)
    ]


def _provenance(input_sha256: str) -> dict:
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


def _formal() -> dict:
    return {
        "ok": True,
        "dataset_tier": "formal_eval_1_0",
        "production_diff": {},
        "core": {
            "record_count": 200,
            "dataset_sha256": "core",
            "metrics": {"ranking": {}, "calibration": {}},
        },
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


def _quality_shadow() -> dict:
    return {
        "shadow_only": True,
        "production_affected": False,
        "window": {"observed_days": 7},
        "high_risk_review": {"sample_count": 0, "reviewed_count": 0},
    }


def _web_clean_eval() -> dict:
    return {
        "version": "web-clean-eval-v2",
        "ok": True,
        "gate": {"result": "GO", "blockers": []},
        "dataset_tier": "web_clean_eval_1_0",
        "manifest_valid": True,
        "dataset_sha256": "dataset-sha",
        "manifest_sha256": "manifest-sha",
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


def _config_and_lock(tmp_path: Path) -> tuple[Path, Path]:
    config = tmp_path / "config.json"
    lock = tmp_path / "lock"
    config.write_text("{}", encoding="utf-8")
    lock.write_text("locked", encoding="utf-8")
    return config, lock


def test_production_label_without_matching_provenance_is_not_release_eligible():
    report = build_web_clean_shadow_report(
        _observations(),
        salt="audit",
        dataset_kind="production_shadow",
    )

    assert report["provenance"]["valid"] is False
    assert report["release_eligible"] is False


def test_shadow_report_accepts_only_matching_export_attestation_and_redacts_samples():
    raw = "\n".join(json.dumps(row, sort_keys=True) for row in _observations()).encode()
    digest = hashlib.sha256(raw).hexdigest()
    report = build_web_clean_shadow_report(
        _observations(),
        salt="audit",
        dataset_kind="production_shadow",
        provenance=_provenance(digest),
        input_sha256=digest,
        provenance_hmac_key=_TEST_PROVENANCE_KEY,
    )

    assert report["provenance"]["valid"] is True
    assert report["release_eligible"] is True
    sample = report["high_risk_review"]["samples"][0]
    assert sample["content_id"] != "content-secret"
    assert "url" not in sample
    assert "full_content" not in sample
    assert "authorization" not in sample


def test_release_gate_rejects_shadow_without_provenance(tmp_path):
    config, lock = _config_and_lock(tmp_path)
    shadow = build_web_clean_shadow_report(
        _observations(),
        salt="audit",
        dataset_kind="production_shadow",
    )

    artifact = build_release_artifact(
        _formal(),
        _quality_shadow(),
        config_path=config,
        lock_path=lock,
        performance={"candidate_pool_p95_ms": 20},
        web_clean=_web_clean_eval(),
        web_clean_shadow=shadow,
        approvers=["owner"],
        commit="abc123",
    )

    assert artifact["decision"]["result"] == "NO_GO"
    assert "Web Clean Shadow production provenance is missing or invalid" in artifact["decision"]["blockers"]


def test_release_gate_requires_formal_blocked_metadata_and_markdown_metrics(tmp_path):
    config, lock = _config_and_lock(tmp_path)
    raw = "\n".join(json.dumps(row, sort_keys=True) for row in _observations()).encode()
    digest = hashlib.sha256(raw).hexdigest()
    shadow = build_web_clean_shadow_report(
        _observations(),
        salt="audit",
        dataset_kind="production_shadow",
        provenance=_provenance(digest),
        input_sha256=digest,
        provenance_hmac_key=_TEST_PROVENANCE_KEY,
    )
    report = _web_clean_eval()
    report["metrics"].update(
        {
            "blocked_detection_f1": 0.0,
            "metadata_accuracy": 0.0,
            "markdown_structure_score": 0.0,
        }
    )

    artifact = build_release_artifact(
        _formal(),
        _quality_shadow(),
        config_path=config,
        lock_path=lock,
        performance={"candidate_pool_p95_ms": 20},
        web_clean=report,
        web_clean_shadow=shadow,
        approvers=["owner"],
        commit="abc123",
        web_clean_provenance_hmac_key=_TEST_PROVENANCE_KEY,
    )

    blockers = artifact["decision"]["blockers"]
    assert artifact["decision"]["result"] == "NO_GO"
    assert any("blocked_detection_f1" in item for item in blockers)
    assert any("metadata_accuracy" in item for item in blockers)
    assert any("markdown_structure_score" in item for item in blockers)


def test_hash_bound_self_attestation_without_trusted_key_is_rejected():
    raw = "\n".join(json.dumps(row, sort_keys=True) for row in _observations()).encode()
    digest = hashlib.sha256(raw).hexdigest()
    provenance = _provenance(digest)

    report = build_web_clean_shadow_report(
        _observations(),
        salt="audit",
        dataset_kind="production_shadow",
        provenance=provenance,
        input_sha256=digest,
    )

    assert report["provenance"]["valid"] is False
    assert report["release_eligible"] is False
