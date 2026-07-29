"""Deterministic, provenance-aware Web Clean golden-fixture evaluation."""

from __future__ import annotations

import hashlib
import json
import statistics
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .contracts import CleanInput
from .extractors import WebDocumentExtractor

_BLOCKED_STATUSES = {"blocked", "login_required", "bot_wall", "captcha"}
_BOOTSTRAP_THRESHOLDS = {
    "sample_count_min": 30,
    "must_include_recall_min": 0.85,
    "boilerplate_leak_rate_max": 0.15,
    "blocked_detection_f1_min": 0.80,
}
_FORMAL_THRESHOLDS = {
    "sample_count_min": 150,
    "must_include_recall_min": 0.90,
    "must_exclude_precision_min": 0.92,
    "boilerplate_leak_rate_max": 0.08,
    "blocked_detection_f1_min": 0.88,
    "metadata_accuracy_min": 0.90,
    "markdown_structure_score_min": 0.85,
    "runtime_multiplier_max": 1.25,
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    dataset_path = Path(path)
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(dataset_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{dataset_path}:{line_number} must be a JSON object")
        rows.append(value)
    return rows


def _fixture_path(row: dict[str, Any], dataset_path: Path) -> Path:
    fixture = row.get("html_fixture")
    if not fixture:
        raise ValueError(f"{row.get('id', '?')}: html or html_fixture is required")
    path = (dataset_path.parent / str(fixture)).resolve()
    root = dataset_path.parent.resolve()
    if root not in path.parents and path != root:
        raise ValueError(f"{row.get('id', '?')}: fixture escapes dataset directory")
    return path


def _fixture_html(row: dict[str, Any], dataset_path: Path) -> str:
    if isinstance(row.get("html"), str):
        return row["html"]
    return _fixture_path(row, dataset_path).read_text(encoding="utf-8")


def _ratio(hits: int, total: int, *, empty: float = 0.0) -> float:
    return round(hits / total, 4) if total else empty


def _normalized_time(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return text


def _markdown_expectations(gold: dict[str, Any]) -> list[str]:
    values = gold.get("markdown_contains") or gold.get("required_markdown") or []
    return [str(item) for item in values] if isinstance(values, list) else []


def _validate_manifest(
    dataset: Path,
    rows: list[dict[str, Any]],
    manifest_path: Path | None,
    tier: str | None,
) -> tuple[dict[str, Any] | None, list[str]]:
    if manifest_path is None:
        return None, ["manifest is missing"]
    if not manifest_path.is_file():
        return None, ["manifest file is missing"]
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return None, [f"manifest is unreadable or invalid JSON: {exc}"]
    if not isinstance(payload, dict):
        return None, ["manifest must be a JSON object"]
    errors: list[str] = []
    dataset_sha = _sha256(dataset)
    if payload.get("dataset_sha256") != dataset_sha:
        errors.append("manifest dataset_sha256 does not match")
    if int(payload.get("sample_count") or -1) != len(rows):
        errors.append("manifest sample_count does not match")
    manifest_tier = str(payload.get("dataset_tier") or "")
    if tier and manifest_tier != tier:
        errors.append("manifest dataset_tier does not match requested tier")
    release_tier = tier or manifest_tier
    if release_tier in {"web_clean_bootstrap", "web_clean_eval_1_0"}:
        inline_rows = [str(row.get("id") or "?") for row in rows if not row.get("html_fixture")]
        if inline_rows:
            errors.append("release-tier rows must use hashed html_fixture files")
        required_fields = ("id", "url", "source_type", "language", "paywall", "case_type", "gold")
        missing_contract = [
            str(row.get("id") or index)
            for index, row in enumerate(rows, start=1)
            if any(row.get(field) in (None, "") for field in required_fields)
        ]
        if missing_contract:
            errors.append("release-tier rows are missing required contract fields")
    if release_tier == "web_clean_eval_1_0":
        languages = {str(row.get("language") or "").lower() for row in rows}
        paywalls = {str(row.get("paywall") or "").lower() for row in rows}
        case_types = {str(row.get("case_type") or "").lower() for row in rows}
        if not {"zh", "en"}.issubset(languages):
            errors.append("formal dataset must cover zh and en")
        if "none" not in paywalls or not (paywalls & {"login_required", "metered", "unknown"}):
            errors.append("formal dataset must cover non-paywalled and paywall/access-control cases")
        required_cases = {"article", "spa", "schema_rich", "table", "code"}
        if not required_cases.issubset(case_types):
            errors.append("formal dataset is missing required case_type coverage")
    fixtures = payload.get("fixtures") or {}
    if not isinstance(fixtures, dict):
        errors.append("manifest fixtures must be an object")
    else:
        referenced = {
            str(row["html_fixture"])
            for row in rows
            if isinstance(row.get("html_fixture"), str) and row.get("html_fixture")
        }
        if set(fixtures) != referenced:
            errors.append("manifest fixture set does not match dataset")
        for relative, expected_sha in fixtures.items():
            try:
                path = _fixture_path({"id": "manifest", "html_fixture": relative}, dataset)
            except ValueError as exc:
                errors.append(str(exc))
                continue
            if not path.is_file() or _sha256(path) != str(expected_sha):
                errors.append(f"fixture hash mismatch: {relative}")
    return payload, errors


def _gate_metrics(
    metrics: dict[str, Any],
    *,
    tier: str | None,
    manifest: dict[str, Any] | None,
    manifest_errors: list[str],
) -> list[str]:
    blockers = list(manifest_errors)
    labels = metrics.get("label_counts") or {}
    if tier in {"web_clean_bootstrap", "web_clean_eval_1_0"}:
        for label in ("must_include", "must_exclude", "quality_status"):
            if int(labels.get(label) or 0) <= 0:
                blockers.append(f"release dataset has no {label} labels")
    if tier == "web_clean_eval_1_0":
        for label in ("title", "canonical_url", "published_time", "markdown"):
            if int(labels.get(label) or 0) <= 0:
                blockers.append(f"formal dataset has no {label} labels")
    if tier == "web_clean_bootstrap":
        thresholds = _BOOTSTRAP_THRESHOLDS
        if metrics["sample_count"] < thresholds["sample_count_min"]:
            blockers.append("bootstrap sample_count is below 30")
        if metrics["must_include_recall"] < thresholds["must_include_recall_min"]:
            blockers.append("bootstrap must_include_recall is below 0.85")
        if metrics["boilerplate_leak_rate"] > thresholds["boilerplate_leak_rate_max"]:
            blockers.append("bootstrap boilerplate_leak_rate exceeds 0.15")
        if metrics["blocked_detection_f1"] < thresholds["blocked_detection_f1_min"]:
            blockers.append("bootstrap blocked_detection_f1 is below 0.80")
    elif tier == "web_clean_eval_1_0":
        thresholds = _FORMAL_THRESHOLDS
        if metrics["sample_count"] < thresholds["sample_count_min"]:
            blockers.append("formal sample_count is below 150")
        if metrics["must_include_recall"] < thresholds["must_include_recall_min"]:
            blockers.append("formal must_include_recall is below 0.90")
        if metrics["must_exclude_precision"] < thresholds["must_exclude_precision_min"]:
            blockers.append("formal must_exclude_precision is below 0.92")
        if metrics["boilerplate_leak_rate"] > thresholds["boilerplate_leak_rate_max"]:
            blockers.append("formal boilerplate_leak_rate exceeds 0.08")
        if metrics["blocked_detection_f1"] < thresholds["blocked_detection_f1_min"]:
            blockers.append("formal blocked_detection_f1 is below 0.88")
        if metrics["metadata_accuracy"] < thresholds["metadata_accuracy_min"]:
            blockers.append("formal metadata_accuracy is below 0.90")
        if metrics["markdown_structure_score"] < thresholds["markdown_structure_score_min"]:
            blockers.append("formal markdown_structure_score is below 0.85")
        baseline = float((manifest or {}).get("baseline_runtime_p95_ms") or 0)
        if baseline <= 0:
            blockers.append("formal manifest baseline_runtime_p95_ms is missing")
        elif metrics["runtime_p95_ms"] > baseline * thresholds["runtime_multiplier_max"]:
            blockers.append("formal runtime_p95_ms exceeds baseline 1.25x")
    else:
        blockers.append("dataset tier is not a release tier")
    return blockers


def evaluate_rows(rows: Iterable[dict[str, Any]], *, dataset_path: str | Path) -> dict[str, Any]:
    dataset = Path(dataset_path)
    extractor = WebDocumentExtractor()
    results: list[dict[str, Any]] = []
    runtimes: list[float] = []
    include_hits = include_total = exclude_hits = exclude_total = 0
    title_hits = title_total = status_hits = status_total = 0
    canonical_hits = canonical_total = published_hits = published_total = 0
    markdown_hits = markdown_total = min_chars_hits = min_chars_total = 0
    blocked_tp = blocked_fp = blocked_fn = 0

    for row in rows:
        html = _fixture_html(row, dataset)
        started = time.perf_counter()
        result = extractor.extract_sync(
            CleanInput(
                url=str(row.get("url") or ""),
                raw_html=html,
                source_metadata=dict(row.get("source_metadata") or {}),
            )
        )
        runtime_ms = (time.perf_counter() - started) * 1000
        runtimes.append(runtime_ms)
        gold = row.get("gold") if isinstance(row.get("gold"), dict) else {}
        body = result.article_text
        must_include = [str(item) for item in gold.get("must_include", [])]
        must_exclude = [str(item) for item in gold.get("must_exclude", [])]
        row_include = sum(1 for item in must_include if item in body)
        row_exclude = sum(1 for item in must_exclude if item not in body)
        include_hits += row_include
        include_total += len(must_include)
        exclude_hits += row_exclude
        exclude_total += len(must_exclude)
        if gold.get("title") is not None:
            title_total += 1
            title_hits += int(result.title == gold.get("title"))
        if gold.get("canonical_url") is not None:
            canonical_total += 1
            canonical_hits += int(result.canonical_url == gold.get("canonical_url"))
        if gold.get("published_time") is not None:
            published_total += 1
            published_hits += int(_normalized_time(result.published_time) == _normalized_time(gold.get("published_time")))
        markdown_expectations = _markdown_expectations(gold)
        markdown_row_hits = sum(1 for item in markdown_expectations if item in result.article_markdown)
        markdown_hits += markdown_row_hits
        markdown_total += len(markdown_expectations)
        if gold.get("min_text_chars") is not None:
            min_chars_total += 1
            min_chars_hits += int(len(body) >= int(gold["min_text_chars"]))
        if gold.get("expected_status") is not None:
            status_total += 1
            expected = str(gold["expected_status"])
            actual = result.quality_status
            expected_blocked = expected in _BLOCKED_STATUSES
            actual_blocked = actual in _BLOCKED_STATUSES
            status_hits += int(actual == expected or (expected_blocked and actual_blocked))
            blocked_tp += int(expected_blocked and actual_blocked)
            blocked_fp += int(not expected_blocked and actual_blocked)
            blocked_fn += int(expected_blocked and not actual_blocked)
        results.append(
            {
                "id": row.get("id"),
                "method": result.extraction_method,
                "status": result.quality_status,
                "score": result.quality_score,
                "text_chars": len(body),
                "runtime_ms": round(runtime_ms, 3),
                "must_include_recall": _ratio(row_include, len(must_include), empty=1.0),
                "must_exclude_precision": _ratio(row_exclude, len(must_exclude), empty=1.0),
                "markdown_structure_score": _ratio(markdown_row_hits, len(markdown_expectations), empty=1.0),
            }
        )

    sorted_runtimes = sorted(runtimes)
    p95_index = max(0, min(len(sorted_runtimes) - 1, int(len(sorted_runtimes) * 0.95) - 1))
    blocked_precision = _ratio(blocked_tp, blocked_tp + blocked_fp)
    blocked_recall = _ratio(blocked_tp, blocked_tp + blocked_fn)
    blocked_f1 = (
        round(2 * blocked_precision * blocked_recall / (blocked_precision + blocked_recall), 4)
        if blocked_precision + blocked_recall
        else 0.0
    )
    metrics = {
        "sample_count": len(results),
        "must_include_recall": _ratio(include_hits, include_total),
        "must_exclude_precision": _ratio(exclude_hits, exclude_total),
        "boilerplate_leak_rate": round(1.0 - _ratio(exclude_hits, exclude_total), 4) if exclude_total else 0.0,
        "title_accuracy": _ratio(title_hits, title_total),
        "canonical_url_accuracy": _ratio(canonical_hits, canonical_total),
        "published_time_accuracy": _ratio(published_hits, published_total),
        "metadata_accuracy": _ratio(
            title_hits + canonical_hits + published_hits,
            title_total + canonical_total + published_total,
        ),
        "quality_status_accuracy": _ratio(status_hits, status_total),
        "markdown_structure_score": _ratio(markdown_hits, markdown_total),
        "minimum_text_accuracy": _ratio(min_chars_hits, min_chars_total),
        "blocked_detection_precision": blocked_precision,
        "blocked_detection_recall": blocked_recall,
        "blocked_detection_f1": blocked_f1,
        "runtime_mean_ms": round(statistics.fmean(runtimes), 3) if runtimes else 0.0,
        "runtime_p95_ms": round(sorted_runtimes[p95_index], 3) if sorted_runtimes else 0.0,
        "label_counts": {
            "must_include": include_total,
            "must_exclude": exclude_total,
            "title": title_total,
            "canonical_url": canonical_total,
            "published_time": published_total,
            "quality_status": status_total,
            "markdown": markdown_total,
        },
    }
    return {"version": "web-clean-eval-v2", "metrics": metrics, "results": results}


def evaluate_jsonl(
    path: str | Path,
    *,
    manifest_path: str | Path | None = None,
    tier: str | None = None,
) -> dict[str, Any]:
    dataset = Path(path)
    rows = load_jsonl(dataset)
    report = evaluate_rows(rows, dataset_path=dataset)
    manifest, manifest_errors = _validate_manifest(
        dataset,
        rows,
        Path(manifest_path) if manifest_path else None,
        tier,
    )
    resolved_tier = tier or str((manifest or {}).get("dataset_tier") or "local")
    blockers = _gate_metrics(
        report["metrics"],
        tier=resolved_tier,
        manifest=manifest,
        manifest_errors=manifest_errors,
    )
    report.update(
        {
            "ok": not blockers,
            "dataset_tier": resolved_tier,
            "dataset_sha256": _sha256(dataset),
            "manifest_sha256": (
                _sha256(Path(manifest_path))
                if manifest_path and Path(manifest_path).is_file()
                else None
            ),
            "manifest_valid": not manifest_errors,
            "gate": {"result": "GO" if not blockers else "NO_GO", "blockers": blockers},
        }
    )
    return report
