from __future__ import annotations

import hashlib
import json

from scripts.check_core_eval_dataset import build_manifest
from scripts.run_formal_eval import (
    FORMAL_RELEASE_SCOPE,
    FORMAL_TIER,
    evaluate_core,
    evaluate_event,
)


def _write_jsonl(path, rows):
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def _formal_fields(dataset):
    return {
        "dataset_tier": FORMAL_TIER,
        "release_scope": FORMAL_RELEASE_SCOPE,
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "git_commit": "abc123",
        "config_version": "formal-v1",
        "sampling_interval": "2026-06-01/2026-07-01",
        "sampling": {"method": "stratified production export"},
        "deidentification": {"reviewed": True},
        "annotation_policy": {"human_review_required": True, "suggested_labels_are_not_final": True},
        "annotators": ["reviewer-a", "reviewer-b"],
        "quality_checks": {"double_review": True},
        "split_policy": {"test": "held out"},
        "limitations": ["small test fixture"],
    }


def _core_row(index, *, label, duplicate=False):
    dimensions = [
        ("website", "en", False, "long", "normal"),
        ("newsletter", "zh", True, "short", "paywall"),
        ("rss", "en", False, "medium", "near_duplicate"),
    ]
    source_type, language, paywall, content_length, case_type = dimensions[index - 1]
    row = {
        "id": f"core-{index}",
        "title": f"Core story {index}",
        "url": f"https://source{index}.example/story",
        "label": label,
        "label_source": "human-review-v1",
        "source_id": f"source-{index}",
        "source_name": f"Source {index}",
        "source_url": f"https://source{index}.example",
        "summary": "A human-reviewed summary.",
        "full_content": "body " * 80,
        "content_type": "website",
        "publish_time": "2026-07-01T00:00:00Z",
        "fetched_at": "2026-07-01T00:10:00Z",
        "metadata": {"fulltext_status": "full"},
        "source_metadata": {},
        "strata": {
            "source_type": source_type,
            "language": language,
            "paywall": paywall,
            "content_length": content_length,
            "case_type": case_type,
        },
    }
    if duplicate:
        row["duplicate_group_id"] = "duplicate-a"
    return row


def test_formal_core_eval_recomputes_pipeline_predictions(tmp_path):
    dataset = tmp_path / "core.jsonl"
    manifest = tmp_path / "core-manifest.json"
    rows = [
        _core_row(1, label="must_see", duplicate=True),
        _core_row(2, label="noise"),
        _core_row(3, label="ok"),
    ]
    _write_jsonl(dataset, rows)
    payload = build_manifest(dataset, rows)
    payload.update(_formal_fields(dataset))
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    report = evaluate_core(dataset, manifest, min_records=3, min_sources=3, top_k=2)

    assert report["ok"] is True
    assert report["metrics"]["classification"]["confusion_matrix"]
    assert report["metrics"]["ranking"]["ndcg@2"] is not None
    assert report["metrics"]["calibration"]["reliability"]
    assert len(report["metrics"]["predictions"]) == 3


def test_formal_core_eval_rejects_prefilled_prediction(tmp_path):
    dataset = tmp_path / "core.jsonl"
    manifest = tmp_path / "core-manifest.json"
    rows = [
        _core_row(1, label="must_see", duplicate=True),
        _core_row(2, label="noise"),
        _core_row(3, label="ok"),
    ]
    rows[0]["article_score"] = 99
    _write_jsonl(dataset, rows)
    payload = build_manifest(dataset, rows)
    payload.update(_formal_fields(dataset))
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    report = evaluate_core(dataset, manifest, min_records=3, min_sources=3)

    assert report["ok"] is False
    assert any("prefilled prediction fields are forbidden" in error for error in report["errors"])


def _event_rows():
    rows = []
    relations = ["same_event", "event_update", "commentary", "duplicate", "unrelated"]
    for index in range(70):
        if index < 20:
            case_type = "cross_language_positive"
            relation = relations[index % 4]
            sequence_id = ""
        elif index < 40:
            case_type = "high_similarity_negative"
            relation = "unrelated"
            sequence_id = ""
        else:
            case_type = ["cross_hour", "cross_day", "same_company_different_event"][index % 3]
            relation = relations[index % len(relations)]
            sequence_id = f"sequence-{index}"
        same = relation != "unrelated"
        left_event = f"event-left-{index}"
        right_event = left_event if same else f"event-right-{index}"
        rows.append(
            {
                "id": f"pair-{index}",
                "relation": relation,
                "case_type": case_type,
                "split": "test" if index % 5 == 0 else "validation",
                "sequence_id": sequence_id,
                "difficult": index == 0,
                "annotators": ["reviewer-a", "reviewer-b"] if index == 0 else ["reviewer-a"],
                "adjudication": {"verdict": relation, "by": "lead"} if index == 0 else {},
                "left": {
                    "id": f"left-{index}",
                    "title": f"Company update {index}",
                    "summary": "Official details.",
                    "language": "zh" if case_type == "cross_language_positive" else "en",
                    "source_role": "originator",
                    "gold_event_id": left_event,
                },
                "right": {
                    "id": f"right-{index}",
                    "title": f"Company update {index if same else index + 1000}",
                    "summary": "Follow-up details.",
                    "language": "en",
                    "source_role": "reporter",
                    "gold_event_id": right_event,
                },
            }
        )
    return rows


def test_formal_event_eval_enforces_contract_and_reports_metrics(tmp_path):
    dataset = tmp_path / "event.jsonl"
    manifest = tmp_path / "event-manifest.json"
    rows = _event_rows()
    _write_jsonl(dataset, rows)
    manifest.write_text(json.dumps(_formal_fields(dataset)), encoding="utf-8")

    report = evaluate_event(dataset, manifest, min_pairs=70, min_clusters=50)

    assert report["ok"] is True
    assert report["metrics"]["pairwise"]["confusion_matrix"]
    assert report["metrics"]["b_cubed_f1"] >= 0
    assert report["metrics"]["id_churn"] is None
    assert report["metrics"]["id_churn_source"].startswith("quality Shadow")
    assert report["metrics"]["evaluation_split"] == "test"
    assert report["metrics"]["strata"]["case_type"]["high_similarity_negative"]["count"] == 4
