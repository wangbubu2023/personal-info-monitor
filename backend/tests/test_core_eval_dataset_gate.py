from __future__ import annotations

import json

from scripts.check_core_eval_dataset import _agent_brief, build_manifest, validate_core_eval_dataset


def _record(idx: int, **overrides):
    base = {
        "id": f"core-{idx}",
        "title": f"Core story {idx}",
        "url": f"https://source{idx}.example/story",
        "label": "ok",
        "label_source": "human-review-sheet-v1",
        "source_id": f"source-{idx}",
        "source_name": f"Source {idx}",
        "source_url": f"https://source{idx}.example",
        "summary": "summary",
        "full_content": "body " * 80,
        "metadata": {"fulltext_status": "full", "fetch_acceptance": "accepted"},
    }
    base.update(overrides)
    return base


def _write_jsonl(path, rows):
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")


def test_core_eval_gate_accepts_installed_dataset_with_manifest(tmp_path):
    dataset = tmp_path / "core_eval_set.jsonl"
    manifest = tmp_path / "core_eval_manifest.json"
    rows = [
        _record(1, label="must_see", duplicate_group_id="event-a"),
        _record(2, label="noise", source_id="source-2", metadata={"fulltext_status": "title_only"}),
        _record(3, label="ok", source_id="source-3"),
    ]
    _write_jsonl(dataset, rows)
    manifest.write_text(
        json.dumps(build_manifest(dataset, rows), ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )

    result = validate_core_eval_dataset(dataset, manifest, min_records=3, min_sources=3)

    assert result.ok
    assert result.errors == []
    assert result.computed_manifest["record_count"] == 3
    assert result.computed_manifest["coverage"]["duplicate_records"] == 1
    assert result.computed_manifest["sample_standard"]["version"] == "core-eval-v1"
    assert result.computed_manifest["annotation_policy"]["human_review_required"] is True
    assert result.computed_manifest["maintenance"]["label_change_rule"]


def test_core_eval_gate_fails_when_dataset_missing(tmp_path):
    result = validate_core_eval_dataset(tmp_path / "missing.jsonl", tmp_path / "manifest.json", min_records=3, min_sources=3)

    assert not result.ok
    assert "core eval dataset is not installed" in result.errors[0]


def test_core_eval_gate_requires_manifest_hash_to_match(tmp_path):
    dataset = tmp_path / "core_eval_set.jsonl"
    manifest = tmp_path / "core_eval_manifest.json"
    rows = [
        _record(1, label="must_see", duplicate_group_id="event-a"),
        _record(2, label="noise", source_id="source-2"),
        _record(3, label="ok", source_id="source-3"),
    ]
    _write_jsonl(dataset, rows)
    payload = build_manifest(dataset, rows)
    payload["dataset_sha256"] = "wrong"
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    result = validate_core_eval_dataset(dataset, manifest, min_records=3, min_sources=3)

    assert not result.ok
    assert any("manifest dataset_sha256 mismatch" in error for error in result.errors)


def test_core_eval_gate_reports_missing_core_coverage(tmp_path):
    dataset = tmp_path / "core_eval_set.jsonl"
    manifest = tmp_path / "core_eval_manifest.json"
    rows = [_record(1), _record(2, source_id="source-2"), _record(3, source_id="source-3")]
    _write_jsonl(dataset, rows)
    manifest.write_text(json.dumps(build_manifest(dataset, rows)), encoding="utf-8")

    result = validate_core_eval_dataset(dataset, manifest, min_records=3, min_sources=3)

    assert not result.ok
    assert "expected at least 2 label classes, found 1" in result.errors
    assert "expected at least one duplicate/near-duplicate marker" in result.errors


def test_core_eval_gate_requires_manifest_maintenance_sections(tmp_path):
    dataset = tmp_path / "core_eval_set.jsonl"
    manifest = tmp_path / "core_eval_manifest.json"
    rows = [
        _record(1, label="must_see", duplicate_group_id="event-a"),
        _record(2, label="noise", source_id="source-2"),
        _record(3, label="ok", source_id="source-3"),
    ]
    _write_jsonl(dataset, rows)
    payload = build_manifest(dataset, rows)
    payload.pop("maintenance")
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    result = validate_core_eval_dataset(dataset, manifest, min_records=3, min_sources=3)

    assert not result.ok
    assert "manifest section 'maintenance' is required" in result.errors


def test_agent_brief_contains_sampling_review_and_install_commands(tmp_path):
    brief = _agent_brief(tmp_path / "core_eval_set.jsonl", tmp_path / "core_eval_manifest.json")

    assert "do not fabricate labels" in brief
    assert "export_eval_candidates.py --limit 500" in brief
    assert "review_eval_candidates.py apply-sheet" in brief
    assert "--require-reviewed" in brief
    assert "check_core_eval_dataset.py" in brief
