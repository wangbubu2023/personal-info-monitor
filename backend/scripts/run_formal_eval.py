#!/usr/bin/env python3
"""Run the fail-closed Core/Event Eval 1.0 suite.

Formal datasets contain human labels and source features only. Predictions are
always recomputed by the current pipeline and emitted into the report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.domains.eval.metrics import (  # noqa: E402
    binary_classification_metrics,
    calibration_metrics,
    cluster_metrics,
    confidence_interval,
    ranking_metrics,
)
from scripts.check_core_eval_dataset import validate_core_eval_dataset  # noqa: E402
from scripts.run_event_cluster_eval import _entry, _load_jsonl  # noqa: E402
from scripts.run_offline_eval import _score_record  # noqa: E402
from app.domains.score.ranking import RankingService  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
DEFAULT_CORE = FIXTURES / "core_eval_1_0.jsonl"
DEFAULT_CORE_MANIFEST = FIXTURES / "core_eval_1_0_manifest.json"
DEFAULT_EVENT = FIXTURES / "event_eval_1_0.jsonl"
DEFAULT_EVENT_MANIFEST = FIXTURES / "event_eval_1_0_manifest.json"
FORMAL_TIER = "formal_eval_1_0"
FORMAL_RELEASE_SCOPE = "algorithm_and_ui_release_gate"
DEFAULT_CONFIG = ROOT / "scripts" / "formal_eval_config.json"
PREDICTION_FIELDS = {"prediction", "predicted_label", "predicted_score", "article_score", "final_score", "score"}
RELATIONS = {"same_event", "event_update", "commentary", "duplicate", "unrelated"}
POSITIVE_RELATIONS = RELATIONS - {"unrelated"}
CORE_STRATA = ("source_type", "language", "paywall", "content_length", "case_type")
EVENT_REQUIRED_CASES = {
    "cross_language_positive",
    "high_similarity_negative",
    "cross_hour",
    "cross_day",
    "same_company_different_event",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_manifest(path: Path, dataset: Path, *, kind: str) -> tuple[dict[str, Any], list[str]]:
    if not path.exists():
        return {}, [f"{kind} manifest is not installed: {path}"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [f"{kind} manifest is invalid: {exc}"]
    errors: list[str] = []
    if payload.get("dataset_tier") != FORMAL_TIER:
        errors.append(f"{kind} manifest dataset_tier must be {FORMAL_TIER}")
    if payload.get("release_scope") != FORMAL_RELEASE_SCOPE:
        errors.append(f"{kind} manifest release_scope must be {FORMAL_RELEASE_SCOPE}")
    if payload.get("dataset_sha256") != _sha256(dataset):
        errors.append(f"{kind} manifest dataset_sha256 mismatch")
    required = (
        "git_commit",
        "config_version",
        "sampling_interval",
        "sampling",
        "deidentification",
        "annotation_policy",
        "annotators",
        "quality_checks",
        "split_policy",
        "limitations",
    )
    for field in required:
        if payload.get(field) in (None, "", [], {}):
            errors.append(f"{kind} manifest {field} is required")
    return payload, errors


def _prefilled_prediction_errors(rows: list[dict[str, Any]], *, kind: str) -> list[str]:
    errors = []
    for index, row in enumerate(rows, start=1):
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        present = sorted(field for field in PREDICTION_FIELDS if field in row or field in metadata)
        if present:
            errors.append(f"{kind} line {index}: prefilled prediction fields are forbidden: {present}")
    return errors


def _stratum(row: dict[str, Any], key: str) -> str:
    strata = row.get("strata") if isinstance(row.get("strata"), dict) else {}
    value = row.get(key, strata.get(key))
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value or "").strip()


def _core_errors(rows: list[dict[str, Any]]) -> list[str]:
    errors = _prefilled_prediction_errors(rows, kind="core")
    for index, row in enumerate(rows, start=1):
        for key in CORE_STRATA:
            if not _stratum(row, key):
                errors.append(f"core line {index}: stratum {key} is required")
        label_source = str(row.get("label_source") or "").lower()
        if not any(marker in label_source for marker in ("human", "manual", "review")):
            errors.append(f"core line {index}: human-reviewed label_source is required")
    for key in CORE_STRATA:
        values = {_stratum(row, key) for row in rows}
        values.discard("")
        if len(values) < 2:
            errors.append(f"core: stratum {key} must contain at least two values")
    return errors


def _core_metrics(rows: list[dict[str, Any]], *, threshold: float, top_k: int) -> dict[str, Any]:
    scores = [_score_record(row) for row in rows]
    truth = [row["label"] in {"must_see", "ok"} for row in rows]
    predictions = [score >= threshold for score in scores]
    relevance = [2.0 if row["label"] == "must_see" else 1.0 if row["label"] == "ok" else 0.0 for row in rows]
    probabilities = [min(1.0, max(0.0, score / 100.0)) for score in scores]
    classification = binary_classification_metrics(truth, predictions)
    ranking = ranking_metrics(relevance, scores, k=top_k)
    calibration = calibration_metrics(truth, probabilities)
    indexed = list(zip(truth, predictions, relevance, scores, strict=True))
    ci = {
        "f1": confidence_interval(
            indexed,
            lambda sample: binary_classification_metrics(
                [item[0] for item in sample], [item[1] for item in sample]
            )["f1"],
        ),
        f"ndcg@{top_k}": confidence_interval(
            indexed,
            lambda sample: ranking_metrics([item[2] for item in sample], [item[3] for item in sample], k=top_k)[
                f"ndcg@{top_k}"
            ],
        ),
    }
    strata: dict[str, dict[str, Any]] = {}
    for key in CORE_STRATA:
        strata[key] = {}
        for value in sorted({_stratum(row, key) for row in rows}):
            indices = [index for index, row in enumerate(rows) if _stratum(row, key) == value]
            strata[key][value] = {
                "count": len(indices),
                **binary_classification_metrics(
                    [truth[index] for index in indices], [predictions[index] for index in indices]
                ),
            }
    failures = [
        {
            "id": row.get("id"),
            "label": row.get("label"),
            "predicted_relevant": predictions[index],
            "score": round(scores[index], 6),
        }
        for index, row in enumerate(rows)
        if truth[index] != predictions[index]
    ]
    return {
        "threshold": threshold,
        "classification": classification,
        "ranking": ranking,
        "calibration": calibration,
        "confidence_intervals": ci,
        "strata": strata,
        "predictions": [
            {"id": row.get("id"), "score": round(scores[index], 6), "predicted_relevant": predictions[index]}
            for index, row in enumerate(rows)
        ],
        "known_failures": failures,
    }


def evaluate_core(
    dataset: Path,
    manifest_path: Path,
    *,
    min_records: int = 200,
    min_sources: int = 10,
    threshold: float = 60.0,
    top_k: int = 20,
) -> dict[str, Any]:
    base = validate_core_eval_dataset(dataset, manifest_path, min_records=min_records, min_sources=min_sources)
    rows = base.records
    errors = list(base.errors)
    manifest: dict[str, Any] = {}
    if dataset.exists():
        manifest, manifest_errors = _read_manifest(manifest_path, dataset, kind="core")
        errors.extend(manifest_errors)
        errors.extend(_core_errors(rows))
    metrics = _core_metrics(rows, threshold=threshold, top_k=top_k) if rows and not errors else None
    return {
        "ok": not errors,
        "dataset": str(dataset),
        "dataset_sha256": _sha256(dataset) if dataset.exists() else None,
        "dataset_tier": FORMAL_TIER,
        "record_count": len(rows),
        "model_version": manifest.get("config_version"),
        "manifest": manifest,
        "metrics": metrics,
        "errors": errors,
    }


def _event_errors(rows: list[dict[str, Any]], *, min_pairs: int, min_clusters: int) -> list[str]:
    errors = _prefilled_prediction_errors(rows, kind="event")
    if len(rows) < min_pairs:
        errors.append(f"event: expected at least {min_pairs} pairs, found {len(rows)}")
    gold_clusters: set[str] = set()
    sequence_ids: set[str] = set()
    case_counts: defaultdict[str, int] = defaultdict(int)
    relation_counts: defaultdict[str, int] = defaultdict(int)
    difficult_adjudicated = 0
    splits: set[str] = set()
    for index, row in enumerate(rows, start=1):
        relation = str(row.get("relation") or "")
        if relation not in RELATIONS:
            errors.append(f"event line {index}: relation must be one of {sorted(RELATIONS)}")
        else:
            relation_counts[relation] += 1
        case_type = str(row.get("case_type") or "")
        case_counts[case_type] += 1
        split = str(row.get("split") or "")
        splits.add(split)
        if split not in {"train", "validation", "test"}:
            errors.append(f"event line {index}: split must be train, validation, or test")
        annotators = row.get("annotators")
        if not isinstance(annotators, list) or not annotators:
            errors.append(f"event line {index}: annotators are required")
        if row.get("difficult"):
            if len(annotators or []) < 2:
                errors.append(f"event line {index}: difficult pairs require two annotators")
            elif not isinstance(row.get("adjudication"), dict) or not row["adjudication"].get("verdict"):
                errors.append(f"event line {index}: difficult pairs require adjudication.verdict")
            else:
                difficult_adjudicated += 1
        sequence_id = str(row.get("sequence_id") or "")
        if sequence_id:
            sequence_ids.add(sequence_id)
        for side in ("left", "right"):
            item = row.get(side)
            if not isinstance(item, dict):
                errors.append(f"event line {index}: {side} must be an object")
                continue
            for field in ("id", "title", "language", "source_role", "gold_event_id"):
                if not str(item.get(field) or "").strip():
                    errors.append(f"event line {index}: {side}.{field} is required")
            if item.get("gold_event_id"):
                gold_clusters.add(str(item["gold_event_id"]))
    if len(gold_clusters) < min_clusters:
        errors.append(f"event: expected at least {min_clusters} gold clusters, found {len(gold_clusters)}")
    if "test" not in splits:
        errors.append("event: independent test split is required")
    if difficult_adjudicated == 0:
        errors.append("event: at least one difficult pair must be double-annotated and adjudicated")
    if len(sequence_ids) < 30:
        errors.append(f"event: expected at least 30 cross-hour/day sequences, found {len(sequence_ids)}")
    if case_counts["high_similarity_negative"] < 20:
        errors.append(
            f"event: expected at least 20 high_similarity_negative pairs, found {case_counts['high_similarity_negative']}"
        )
    if case_counts["cross_language_positive"] < 20:
        errors.append(
            f"event: expected at least 20 cross_language_positive pairs, found {case_counts['cross_language_positive']}"
        )
    for case_type in sorted(EVENT_REQUIRED_CASES):
        if case_counts[case_type] == 0:
            errors.append(f"event: missing case_type={case_type}")
    for relation in sorted(RELATIONS):
        if relation_counts[relation] == 0:
            errors.append(f"event: missing relation={relation}")
    return errors


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, item: str) -> str:
        self.parent.setdefault(item, item)
        if self.parent[item] != item:
            self.parent[item] = self.find(self.parent[item])
        return self.parent[item]

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def _event_metrics(rows: list[dict[str, Any]], *, threshold: float) -> dict[str, Any]:
    service = RankingService(similarity_threshold=threshold)
    expected: list[bool] = []
    predicted: list[bool] = []
    predicted_union = _UnionFind()
    gold_assignments: dict[str, str] = {}
    cases = []
    for row in rows:
        left = row["left"]
        right = row["right"]
        clusters = service.cluster_and_rank([_entry(left), _entry(right)])
        guessed = len(clusters) == 1
        truth = row["relation"] in POSITIVE_RELATIONS
        expected.append(truth)
        predicted.append(guessed)
        left_id = str(left["id"])
        right_id = str(right["id"])
        predicted_union.find(left_id)
        predicted_union.find(right_id)
        if guessed:
            predicted_union.union(left_id, right_id)
        gold_assignments[left_id] = str(left["gold_event_id"])
        gold_assignments[right_id] = str(right["gold_event_id"])
        cases.append(
            {
                "id": row.get("id"),
                "relation": row.get("relation"),
                "expected_same": truth,
                "predicted_same": guessed,
                "case_type": row.get("case_type"),
                "split": row.get("split"),
            }
        )
    pair = binary_classification_metrics(expected, predicted)
    predicted_assignments = {item_id: predicted_union.find(item_id) for item_id in gold_assignments}
    clustered = cluster_metrics(gold_assignments, predicted_assignments)
    confusion = pair["confusion_matrix"]

    def sliced(indices: list[int]) -> dict[str, Any]:
        return {
            "count": len(indices),
            **binary_classification_metrics(
                [expected[index] for index in indices], [predicted[index] for index in indices]
            ),
        }

    strata: dict[str, dict[str, Any]] = {}
    for key in ("case_type", "relation", "split"):
        values = sorted({str(row.get(key) or "") for row in rows})
        strata[key] = {
            value: sliced([index for index, row in enumerate(rows) if str(row.get(key) or "") == value])
            for value in values
        }
    language_values = sorted(
        {f"{row['left'].get('language')}->{row['right'].get('language')}" for row in rows}
    )
    strata["language_pair"] = {
        value: sliced(
            [
                index
                for index, row in enumerate(rows)
                if f"{row['left'].get('language')}->{row['right'].get('language')}" == value
            ]
        )
        for value in language_values
    }
    role_values = sorted(
        {f"{row['left'].get('source_role')}->{row['right'].get('source_role')}" for row in rows}
    )
    strata["source_role_pair"] = {
        value: sliced(
            [
                index
                for index, row in enumerate(rows)
                if f"{row['left'].get('source_role')}->{row['right'].get('source_role')}" == value
            ]
        )
        for value in role_values
    }
    sequence_indices = [index for index, row in enumerate(rows) if row.get("sequence_id") and expected[index]]
    continuity = (
        sum(1 for index in sequence_indices if predicted[index]) / len(sequence_indices) if sequence_indices else 0.0
    )
    known_failures = [case for index, case in enumerate(cases) if expected[index] != predicted[index]]
    return {
        "threshold": threshold,
        "pairwise": pair,
        "b_cubed_precision": clustered["b_cubed_precision"],
        "b_cubed_recall": clustered["b_cubed_recall"],
        "b_cubed_f1": clustered["b_cubed_f1"],
        "id_churn": None,
        "id_churn_source": "quality Shadow v0/v1 stable assignment diff",
        "wrong_merge_rate": round(confusion["fp"] / max(1, confusion["tp"] + confusion["fp"]), 6),
        "missing_merge_rate": round(confusion["fn"] / max(1, confusion["tp"] + confusion["fn"]), 6),
        "merge_split_recommendation_precision": pair["precision"],
        "cross_hour_continuity": round(continuity, 6),
        "strata": strata,
        "cases": cases,
        "known_failures": known_failures,
    }


def evaluate_event(
    dataset: Path,
    manifest_path: Path,
    *,
    min_pairs: int = 200,
    min_clusters: int = 50,
    threshold: float = 0.28,
) -> dict[str, Any]:
    if not dataset.exists():
        return {
            "ok": False,
            "dataset": str(dataset),
            "dataset_sha256": None,
            "dataset_tier": FORMAL_TIER,
            "pair_count": 0,
            "metrics": None,
            "errors": [f"event eval dataset is not installed: {dataset}"],
        }
    rows = _load_jsonl(dataset)
    manifest, errors = _read_manifest(manifest_path, dataset, kind="event")
    errors.extend(_event_errors(rows, min_pairs=min_pairs, min_clusters=min_clusters))
    test_rows = [row for row in rows if row.get("split") == "test"]
    metrics = _event_metrics(test_rows, threshold=threshold) if test_rows and not errors else None
    if metrics is not None:
        metrics["evaluation_split"] = "test"
        metrics["evaluation_pair_count"] = len(test_rows)
    return {
        "ok": not errors,
        "dataset": str(dataset),
        "dataset_sha256": _sha256(dataset),
        "dataset_tier": FORMAL_TIER,
        "pair_count": len(rows),
        "test_pair_count": len(test_rows),
        "model_version": manifest.get("config_version"),
        "manifest": manifest,
        "metrics": metrics,
        "errors": errors,
    }


def compare_reports(current: dict[str, Any], baseline: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return numeric metric deltas for a compatible production baseline."""

    if not baseline:
        return None

    def flatten(payload: Any, prefix: str = "") -> dict[str, float]:
        result: dict[str, float] = {}
        if isinstance(payload, dict):
            for key, value in payload.items():
                path = f"{prefix}.{key}" if prefix else key
                result.update(flatten(value, path))
        elif isinstance(payload, (int, float)) and not isinstance(payload, bool) and math.isfinite(float(payload)):
            result[prefix] = float(payload)
        return result

    current_values = flatten(current)
    baseline_values = flatten(baseline)
    return {
        key: round(current_values[key] - baseline_values[key], 6)
        for key in sorted(current_values.keys() & baseline_values.keys())
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run formal Core/Event Eval 1.0")
    parser.add_argument("--core", type=Path, default=DEFAULT_CORE)
    parser.add_argument("--core-manifest", type=Path, default=DEFAULT_CORE_MANIFEST)
    parser.add_argument("--event", type=Path, default=DEFAULT_EVENT)
    parser.add_argument("--event-manifest", type=Path, default=DEFAULT_EVENT_MANIFEST)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--min-core-records", type=int)
    parser.add_argument("--min-core-sources", type=int)
    parser.add_argument("--min-event-pairs", type=int)
    parser.add_argument("--min-event-clusters", type=int)
    parser.add_argument("--score-threshold", type=float)
    parser.add_argument("--event-threshold", type=float)
    parser.add_argument("--top-k", type=int)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    core_config = config["core"]
    event_config = config["event"]
    min_core_records = args.min_core_records or int(core_config["minimum_records"])
    min_core_sources = args.min_core_sources or int(core_config["minimum_sources"])
    min_event_pairs = args.min_event_pairs or int(event_config["minimum_pairs"])
    min_event_clusters = args.min_event_clusters or int(event_config["minimum_clusters"])
    score_threshold = args.score_threshold if args.score_threshold is not None else float(
        core_config["classification_threshold"]
    )
    event_threshold = args.event_threshold if args.event_threshold is not None else float(
        event_config["similarity_threshold"]
    )
    top_k = args.top_k or int(core_config["top_k"])

    core = evaluate_core(
        args.core,
        args.core_manifest,
        min_records=min_core_records,
        min_sources=min_core_sources,
        threshold=score_threshold,
        top_k=top_k,
    )
    event = evaluate_event(
        args.event,
        args.event_manifest,
        min_pairs=min_event_pairs,
        min_clusters=min_event_clusters,
        threshold=event_threshold,
    )
    baseline = json.loads(args.baseline.read_text(encoding="utf-8")) if args.baseline else None
    baseline_metrics = None
    if baseline:
        baseline_metrics = {
            "core": (baseline.get("core") or {}).get("metrics"),
            "event": (baseline.get("event") or {}).get("metrics"),
        }
    payload = {
        "ok": core["ok"] and event["ok"],
        "dataset_tier": FORMAL_TIER,
        "release_scope": FORMAL_RELEASE_SCOPE,
        "config": str(args.config),
        "config_sha256": _sha256(args.config),
        "core": core,
        "event": event,
        "production_diff": compare_reports(
            {"core": core.get("metrics"), "event": event.get("metrics")},
            baseline_metrics,
        ),
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
