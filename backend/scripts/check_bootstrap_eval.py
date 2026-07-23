#!/usr/bin/env python3
"""Fail-closed M0/M1 gate for real, human-reviewed bootstrap datasets."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.check_core_eval_dataset import validate_core_eval_dataset
from scripts.run_event_cluster_eval import _load_jsonl, validate_event_cluster_dataset
from scripts.run_offline_eval import run_offline_eval

FIXTURES = ROOT / "tests" / "fixtures"
DEFAULT_CORE = FIXTURES / "core_bootstrap_v0_1.jsonl"
DEFAULT_CORE_MANIFEST = FIXTURES / "core_bootstrap_v0_1_manifest.json"
DEFAULT_EVENT = FIXTURES / "event_bootstrap_v0_1.jsonl"
DEFAULT_EVENT_MANIFEST = FIXTURES / "event_bootstrap_v0_1_manifest.json"
BOOTSTRAP_RELEASE_SCOPE = "m0_m1_infrastructure_only"
EVENT_BOOTSTRAP_CASES = {
    "same_entity_different_event",
    "cross_hour",
    "repost",
    "rumor_denial",
    "high_similarity_negative",
}
PREDICTION_FIELDS = {"prediction", "predicted_label", "predicted_score", "article_score", "final_score", "score"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest_errors(path: Path, dataset: Path, *, kind: str) -> list[str]:
    if not path.exists():
        return [f"{kind} bootstrap manifest is not installed: {path}"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{kind} bootstrap manifest is invalid: {exc}"]
    errors: list[str] = []
    if payload.get("dataset_tier") != "bootstrap":
        errors.append(f"{kind} manifest dataset_tier must be bootstrap")
    if payload.get("release_scope") != BOOTSTRAP_RELEASE_SCOPE:
        errors.append(f"{kind} manifest release_scope must be {BOOTSTRAP_RELEASE_SCOPE}")
    if payload.get("dataset_sha256") != _sha256(dataset):
        errors.append(f"{kind} manifest dataset_sha256 mismatch")
    for field in ("git_commit", "sampling_interval", "deidentification", "annotation_policy", "annotators", "limitations"):
        value = payload.get(field)
        if value is None or value == "" or value == [] or value == {}:
            errors.append(f"{kind} manifest {field} is required")
    return errors


def _prediction_errors(rows: list[dict[str, Any]], *, kind: str) -> list[str]:
    errors: list[str] = []
    for idx, row in enumerate(rows, start=1):
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        present = sorted(field for field in PREDICTION_FIELDS if field in row or field in metadata)
        if present:
            errors.append(f"{kind} line {idx}: prefilled prediction fields are forbidden: {present}")
        label_source = str(row.get("label_source") or "").lower()
        if not any(marker in label_source for marker in ("human", "manual", "review")):
            errors.append(f"{kind} line {idx}: human-reviewed label_source is required")
    return errors


def check_bootstrap_eval(
    core: Path = DEFAULT_CORE,
    core_manifest: Path = DEFAULT_CORE_MANIFEST,
    event: Path = DEFAULT_EVENT,
    event_manifest: Path = DEFAULT_EVENT_MANIFEST,
) -> dict[str, Any]:
    errors: list[str] = []
    core_rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []

    core_result = validate_core_eval_dataset(core, core_manifest, min_records=50, min_sources=3)
    errors.extend(f"core: {error}" for error in core_result.errors)
    core_rows = core_result.records
    if core.exists():
        errors.extend(_manifest_errors(core_manifest, core, kind="core"))
        errors.extend(_prediction_errors(core_rows, kind="core"))

    if not event.exists():
        errors.append(f"event bootstrap dataset is not installed: {event}")
    else:
        event_rows = _load_jsonl(event)
        errors.extend(f"event: {error}" for error in validate_event_cluster_dataset(event_rows, min_pairs=50, min_clusters=15))
        case_types = {str(row.get("case_type") or "") for row in event_rows}
        for missing in sorted(EVENT_BOOTSTRAP_CASES - case_types):
            errors.append(f"event: missing bootstrap case_type={missing}")
        errors.extend(_manifest_errors(event_manifest, event, kind="event"))
        errors.extend(_prediction_errors(event_rows, kind="event"))

    metrics = None
    if not errors:
        # Bootstrap rows cannot contain prediction fields, so this necessarily
        # invokes the current scoring pipeline rather than reading a fixture score.
        metrics = run_offline_eval(core, history_path=None, append_history=False)["metrics"]
    return {
        "ok": not errors,
        "dataset_tier": "bootstrap",
        "release_scope": BOOTSTRAP_RELEASE_SCOPE,
        "core_records": len(core_rows),
        "event_pairs": len(event_rows),
        "core_sha256": _sha256(core) if core.exists() else None,
        "event_sha256": _sha256(event) if event.exists() else None,
        "metrics": metrics,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--core", type=Path, default=DEFAULT_CORE)
    parser.add_argument("--core-manifest", type=Path, default=DEFAULT_CORE_MANIFEST)
    parser.add_argument("--event", type=Path, default=DEFAULT_EVENT)
    parser.add_argument("--event-manifest", type=Path, default=DEFAULT_EVENT_MANIFEST)
    args = parser.parse_args()
    result = check_bootstrap_eval(args.core, args.core_manifest, args.event, args.event_manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
