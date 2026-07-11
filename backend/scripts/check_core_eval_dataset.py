#!/usr/bin/env python3
"""Validate that the shared Core Eval dataset has been installed.

This is a CI gate for P1-01's engineering side. It intentionally does not
manufacture labels: until a human-reviewed dataset is installed, this script
fails with a clear next step instead of silently running the tiny unit-test
fixture as if it were the shared eval set.

The sample contract lives in this file on purpose. Future agents should treat
``CORE_EVAL_SAMPLE_STANDARD`` as the source of truth for what to sample, how to
label, how to install, and how the dataset should be maintained.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)

from scripts.run_offline_eval import VALID_LABELS, compute_metrics

DEFAULT_CORE_EVAL_SET = Path(backend_dir) / "tests" / "fixtures" / "core_eval_set.jsonl"
DEFAULT_MANIFEST = Path(backend_dir) / "tests" / "fixtures" / "core_eval_manifest.json"
DEFAULT_MIN_RECORDS = 200
DEFAULT_MIN_SOURCES = 10
MIN_LABEL_CLASSES = 2
REQUIRED_FIELDS = (
    "id",
    "title",
    "url",
    "label",
    "label_source",
    "source_id",
    "source_name",
    "source_url",
)
REQUIRED_MANIFEST_SECTIONS = ("sample_standard", "sampling", "annotation_policy", "maintenance")

CORE_EVAL_SAMPLE_STANDARD: dict[str, Any] = {
    "version": "core-eval-v1",
    "purpose": (
        "Shared, de-identified, human-reviewed quality eval for PIM scoring, "
        "fulltext quality, near-duplicate behavior, and future event/rule coverage."
    ),
    "minimums": {
        "records": DEFAULT_MIN_RECORDS,
        "sources": DEFAULT_MIN_SOURCES,
        "label_classes": MIN_LABEL_CLASSES,
    },
    "required_record_fields": list(REQUIRED_FIELDS)
    + [
        "summary",
        "full_content",
        "content_type",
        "publish_time",
        "fetched_at",
        "metadata",
        "source_metadata",
    ],
    "labels": {
        "must_see": "High-signal item a good daily brief should surface.",
        "ok": "Relevant or useful, but not necessarily a top daily item.",
        "noise": "Duplicate, low-signal, promotional, irrelevant, or poor-quality extraction.",
    },
    "coverage_targets": {
        "fulltext_quality": "metadata.fulltext_status/fetch_acceptance must be present across the set.",
        "near_duplicate": "Include duplicate_group_id/is_duplicate_of/duplicate_of examples.",
        "event_grouping": "Prefer event_id/event_key when available; report as pending if the production model has not landed yet.",
        "rule_coverage": "Prefer rule_id/rule_matches/keyword_matches when available; report as pending if rules are not yet exported.",
    },
    "privacy_rules": [
        "No cookies, API keys, auth headers, browser storage, private tokens, or runtime secrets.",
        "No private emails, chat logs, personal notes, or non-public user identifiers unless irreversibly redacted.",
        "Full content must be truncated to the export limit and should only include content the user is allowed to process locally.",
        "Keep source attribution, title, timestamps, and URL so eval failures remain debuggable.",
    ],
    "agent_sampling_brief": [
        "In the production PIM environment, export around 500 recent diverse candidates across at least 10 sources.",
        "Use scripts/export_eval_candidates.py with blank labels; do not invent final labels automatically.",
        "Run scripts/prelabel_eval_candidates.py only to add suggested_* review hints.",
        "Create a TSV or HTML review sheet with scripts/review_eval_candidates.py; ask the human to confirm/fix labels.",
        "Apply the reviewed sheet with --require-reviewed, then validate/install the JSONL and write a manifest.",
        "If event/rule fields are unavailable, leave coverage in the manifest as zero/pending instead of fabricating fields.",
    ],
    "maintenance_policy": {
        "refresh_cadence": "Refresh or extend the dataset after major scoring/dedupe/event/rule changes, or monthly during active eval work.",
        "append_only_default": "Prefer adding a new versioned dataset/manifest over silently rewriting old labels.",
        "label_change_rule": "Changing an existing label requires annotation_notes explaining why.",
        "history": "Keep prior eval_history metrics so threshold movement is explainable.",
    },
}


def _agent_brief(dataset_path: Path = DEFAULT_CORE_EVAL_SET, manifest_path: Path = DEFAULT_MANIFEST) -> str:
    data_dir = "~/.pim/data"
    lines = [
        "Core Eval agent brief:",
        "1. Goal: build a human-reviewed shared Core Eval dataset; do not fabricate labels.",
        "2. Sample standard:",
        f"   - minimum records: {DEFAULT_MIN_RECORDS}",
        f"   - minimum sources: {DEFAULT_MIN_SOURCES}",
        f"   - valid labels: {', '.join(sorted(VALID_LABELS))}",
        "   - required fields: " + ", ".join(CORE_EVAL_SAMPLE_STANDARD["required_record_fields"]),
        "   - include fulltext quality markers and near-duplicate examples.",
        "   - event/rule fields are preferred; if absent, record coverage as pending/zero, never invent them.",
        "3. Production sampling workflow:",
        f"   cd backend && uv run python scripts/export_eval_candidates.py --limit 500 --min-records {DEFAULT_MIN_RECORDS} --max-days 365 --output {data_dir}/core_eval_candidates.jsonl",
        f"   uv run python scripts/prelabel_eval_candidates.py {data_dir}/core_eval_candidates.jsonl --output {data_dir}/core_eval_prelabeled.jsonl",
        f"   uv run python scripts/review_eval_candidates.py export-html {data_dir}/core_eval_prelabeled.jsonl --output {data_dir}/core_eval_review.html",
        f"   uv run python scripts/review_eval_candidates.py export-sheet {data_dir}/core_eval_prelabeled.jsonl --output {data_dir}/core_eval_review.tsv",
        f"   # Human reviews labels in the sheet/html, then:",
        f"   uv run python scripts/review_eval_candidates.py apply-sheet {data_dir}/core_eval_prelabeled.jsonl --sheet {data_dir}/core_eval_review.tsv --output {data_dir}/core_eval_labeled.jsonl --require-reviewed",
        f"   uv run python scripts/validate_eval_set.py {data_dir}/core_eval_labeled.jsonl --min-records {DEFAULT_MIN_RECORDS} --min-sources {DEFAULT_MIN_SOURCES}",
        f"   cp {data_dir}/core_eval_labeled.jsonl {dataset_path}",
        f"   uv run python scripts/check_core_eval_dataset.py --dataset {dataset_path} --manifest {manifest_path} --write-manifest",
        "4. Maintenance:",
        "   - add a new versioned dataset after major scoring/dedupe/event/rule changes or monthly during active work;",
        "   - explain any changed existing label in annotation_notes;",
        "   - keep eval_history and threshold changes reviewable.",
    ]
    return "\n".join(lines)


@dataclass(frozen=True)
class CoreEvalValidationResult:
    records: list[dict[str, Any]]
    errors: list[str]
    manifest: dict[str, Any] | None
    computed_manifest: dict[str, Any]

    @property
    def ok(self) -> bool:
        return not self.errors


def _load_jsonl(path: Path) -> list[tuple[int, dict[str, Any]]]:
    rows: list[tuple[int, dict[str, Any]]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            try:
                record = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"{path}:{line_no}: record must be a JSON object")
            rows.append((line_no, record))
    return rows


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: manifest must be a JSON object")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(Path(backend_dir).parent), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def _source_key(record: dict[str, Any]) -> str:
    return str(record.get("source_id") or record.get("source_url") or record.get("source_name") or "").strip()


def _has_duplicate_marker(record: dict[str, Any]) -> bool:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    return bool(
        record.get("duplicate_group_id")
        or record.get("is_duplicate_of")
        or record.get("duplicate_of")
        or metadata.get("duplicate_group_id")
    )


def _has_event_marker(record: dict[str, Any]) -> bool:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    return bool(record.get("event_id") or record.get("event_key") or metadata.get("event_id") or metadata.get("event_key"))


def _has_rule_marker(record: dict[str, Any]) -> bool:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    return bool(
        record.get("rule_id")
        or record.get("rule_matches")
        or record.get("keyword_matches")
        or metadata.get("rule_id")
        or metadata.get("rule_matches")
        or metadata.get("keyword_matches")
    )


def _has_fulltext_quality_marker(record: dict[str, Any]) -> bool:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    return bool(metadata.get("fulltext_status") or metadata.get("fetch_acceptance") or "full_content" in record)


def build_manifest(dataset_path: Path, records: list[dict[str, Any]]) -> dict[str, Any]:
    labels = Counter(str(record.get("label") or "").strip() for record in records)
    labels.pop("", None)
    label_sources = Counter(str(record.get("label_source") or "").strip() for record in records)
    label_sources.pop("", None)
    sources = {_source_key(record) for record in records}
    sources.discard("")
    metrics = compute_metrics(records) if records else {}
    coverage = {
        "fulltext_quality_records": sum(1 for record in records if _has_fulltext_quality_marker(record)),
        "duplicate_records": sum(1 for record in records if _has_duplicate_marker(record)),
        "event_records": sum(1 for record in records if _has_event_marker(record)),
        "rule_records": sum(1 for record in records if _has_rule_marker(record)),
    }
    return {
        "dataset": dataset_path.name,
        "dataset_sha256": _sha256(dataset_path),
        "record_count": len(records),
        "source_count": len(sources),
        "label_counts": dict(sorted(labels.items())),
        "label_sources": dict(sorted(label_sources.items())),
        "coverage": coverage,
        "metrics": metrics,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(),
        "sample_standard": CORE_EVAL_SAMPLE_STANDARD,
        "sampling": {
            "source": "production PIM export via scripts/export_eval_candidates.py",
            "recommended_candidate_count": 500,
            "candidate_review_required": True,
            "agent_brief_command": "python scripts/check_core_eval_dataset.py --print-agent-brief",
        },
        "annotation_policy": {
            "human_review_required": True,
            "valid_labels": sorted(VALID_LABELS),
            "label_source_required": True,
            "suggested_labels_are_not_final": True,
            "label_change_requires_annotation_notes": True,
        },
        "maintenance": CORE_EVAL_SAMPLE_STANDARD["maintenance_policy"],
        "config": {
            "min_records": DEFAULT_MIN_RECORDS,
            "min_sources": DEFAULT_MIN_SOURCES,
            "valid_labels": sorted(VALID_LABELS),
            "note": "Event/rule coverage may be zero until the next annotation pass; this gate verifies installation, hash, and quality labels.",
        },
    }


def _validate_manifest_contract(manifest: dict[str, Any], errors: list[str]) -> None:
    for section in REQUIRED_MANIFEST_SECTIONS:
        if not isinstance(manifest.get(section), dict):
            errors.append(f"manifest section {section!r} is required")
    annotation_policy = manifest.get("annotation_policy") if isinstance(manifest.get("annotation_policy"), dict) else {}
    if annotation_policy.get("human_review_required") is not True:
        errors.append("manifest annotation_policy.human_review_required must be true")
    if annotation_policy.get("suggested_labels_are_not_final") is not True:
        errors.append("manifest annotation_policy.suggested_labels_are_not_final must be true")
    maintenance = manifest.get("maintenance") if isinstance(manifest.get("maintenance"), dict) else {}
    if not str(maintenance.get("refresh_cadence") or "").strip():
        errors.append("manifest maintenance.refresh_cadence is required")
    if not str(maintenance.get("label_change_rule") or "").strip():
        errors.append("manifest maintenance.label_change_rule is required")


def validate_core_eval_dataset(
    dataset_path: Path = DEFAULT_CORE_EVAL_SET,
    manifest_path: Path = DEFAULT_MANIFEST,
    *,
    min_records: int = DEFAULT_MIN_RECORDS,
    min_sources: int = DEFAULT_MIN_SOURCES,
) -> CoreEvalValidationResult:
    errors: list[str] = []
    if not dataset_path.exists():
        return CoreEvalValidationResult(
            records=[],
            errors=[
                f"core eval dataset is not installed: {dataset_path}",
                "install a human-reviewed JSONL dataset with scripts/validate_eval_set.py or copy the reviewed set to tests/fixtures/core_eval_set.jsonl",
                "ask the production agent to run: python scripts/check_core_eval_dataset.py --print-agent-brief",
            ],
            manifest=None,
            computed_manifest={},
        )
    rows = _load_jsonl(dataset_path)
    records = [record for _, record in rows]
    seen_ids: dict[str, int] = {}
    sources: set[str] = set()
    labels: Counter[str] = Counter()

    if len(records) < min_records:
        errors.append(f"expected at least {min_records} records, found {len(records)}")

    for line_no, record in rows:
        for field in REQUIRED_FIELDS:
            if not str(record.get(field) or "").strip():
                errors.append(f"line {line_no}: {field} is required")
        record_id = str(record.get("id") or "").strip()
        if record_id:
            if record_id in seen_ids:
                errors.append(f"line {line_no}: duplicate id {record_id!r}; first seen on line {seen_ids[record_id]}")
            else:
                seen_ids[record_id] = line_no
        label = str(record.get("label") or "").strip()
        if label:
            if label not in VALID_LABELS:
                errors.append(f"line {line_no}: label must be one of {sorted(VALID_LABELS)}")
            else:
                labels[label] += 1
        source_key = _source_key(record)
        if source_key:
            sources.add(source_key)

    if len(sources) < min_sources:
        errors.append(f"expected at least {min_sources} sources, found {len(sources)}")
    if len(labels) < MIN_LABEL_CLASSES:
        errors.append(f"expected at least {MIN_LABEL_CLASSES} label classes, found {len(labels)}")
    if not any(_has_fulltext_quality_marker(record) for record in records):
        errors.append("expected fulltext quality markers such as metadata.fulltext_status or metadata.fetch_acceptance")
    if not any(_has_duplicate_marker(record) for record in records):
        errors.append("expected at least one duplicate/near-duplicate marker")

    computed_manifest = build_manifest(dataset_path, records) if records else {}
    manifest = None
    if not manifest_path.exists():
        errors.append(f"core eval manifest is not installed: {manifest_path}")
    else:
        manifest = _load_manifest(manifest_path)
        _validate_manifest_contract(manifest, errors)
        expected_sha = str(manifest.get("dataset_sha256") or "").strip()
        if expected_sha != computed_manifest.get("dataset_sha256"):
            errors.append(
                f"manifest dataset_sha256 mismatch: manifest={expected_sha or '<missing>'} actual={computed_manifest.get('dataset_sha256')}"
            )
        expected_count = manifest.get("record_count")
        if expected_count != computed_manifest.get("record_count"):
            errors.append(
                f"manifest record_count mismatch: manifest={expected_count!r} actual={computed_manifest.get('record_count')}"
            )

    return CoreEvalValidationResult(
        records=records,
        errors=errors,
        manifest=manifest,
        computed_manifest=computed_manifest,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the installed shared PIM Core Eval dataset")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_CORE_EVAL_SET)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--min-records", type=int, default=DEFAULT_MIN_RECORDS)
    parser.add_argument("--min-sources", type=int, default=DEFAULT_MIN_SOURCES)
    parser.add_argument("--write-manifest", action="store_true", help="Write/update manifest for the dataset")
    parser.add_argument("--print-agent-brief", action="store_true", help="Print production-agent sampling and review instructions")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.print_agent_brief:
        print(_agent_brief(args.dataset, args.manifest))
        return 0

    result = validate_core_eval_dataset(
        args.dataset,
        args.manifest,
        min_records=args.min_records,
        min_sources=args.min_sources,
    )
    if args.write_manifest:
        if not result.records:
            print(f"cannot write manifest without dataset: {args.dataset}", file=sys.stderr)
            print(_agent_brief(args.dataset, args.manifest))
            return 1
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(
            json.dumps(result.computed_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        result = validate_core_eval_dataset(
            args.dataset,
            args.manifest,
            min_records=args.min_records,
            min_sources=args.min_sources,
        )

    payload = {
        "ok": result.ok,
        "dataset": str(args.dataset),
        "manifest": str(args.manifest),
        "records": len(result.records),
        "errors": result.errors,
        "computed_manifest": result.computed_manifest,
        "agent_brief_command": "python scripts/check_core_eval_dataset.py --print-agent-brief",
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        status = "passed" if result.ok else "failed"
        print(f"core eval dataset gate {status}")
        if result.computed_manifest:
            print(f"  records: {result.computed_manifest['record_count']}")
            print(f"  sources: {result.computed_manifest['source_count']}")
            print(f"  sha256: {result.computed_manifest['dataset_sha256']}")
            print(f"  labels: {result.computed_manifest['label_counts']}")
            print(f"  coverage: {result.computed_manifest['coverage']}")
        for error in result.errors:
            print(f"  error: {error}", file=sys.stderr)
        if not result.ok:
            print("\n" + _agent_brief(args.dataset, args.manifest))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
