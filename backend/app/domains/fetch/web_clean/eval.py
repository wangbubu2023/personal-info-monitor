"""Deterministic Web Clean golden-fixture evaluation."""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path
from typing import Any, Iterable

from .contracts import CleanInput
from .extractors import WebDocumentExtractor


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


def _fixture_html(row: dict[str, Any], dataset_path: Path) -> str:
    if isinstance(row.get("html"), str):
        return row["html"]
    fixture = row.get("html_fixture")
    if not fixture:
        raise ValueError(f"{row.get('id', '?')}: html or html_fixture is required")
    path = (dataset_path.parent / str(fixture)).resolve()
    root = dataset_path.parent.resolve()
    if root not in path.parents and path != root:
        raise ValueError(f"{row.get('id', '?')}: fixture escapes dataset directory")
    return path.read_text(encoding="utf-8")


def _ratio(hits: int, total: int, *, empty: float = 1.0) -> float:
    return round(hits / total, 4) if total else empty


def evaluate_rows(rows: Iterable[dict[str, Any]], *, dataset_path: str | Path) -> dict[str, Any]:
    dataset = Path(dataset_path)
    extractor = WebDocumentExtractor()
    results: list[dict[str, Any]] = []
    runtimes: list[float] = []
    include_hits = include_total = exclude_hits = exclude_total = 0
    title_hits = title_total = status_hits = status_total = 0

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
        if gold.get("expected_status") is not None:
            status_total += 1
            expected = str(gold["expected_status"])
            actual = result.quality_status
            status_hits += int(actual == expected or (expected == "blocked" and actual in {"login_required", "bot_wall", "captcha"}))
        results.append(
            {
                "id": row.get("id"),
                "method": result.extraction_method,
                "status": result.quality_status,
                "score": result.quality_score,
                "text_chars": len(body),
                "runtime_ms": round(runtime_ms, 3),
                "must_include_recall": _ratio(row_include, len(must_include)),
                "must_exclude_precision": _ratio(row_exclude, len(must_exclude)),
            }
        )

    sorted_runtimes = sorted(runtimes)
    p95_index = max(0, min(len(sorted_runtimes) - 1, int(len(sorted_runtimes) * 0.95) - 1))
    metrics = {
        "sample_count": len(results),
        "must_include_recall": _ratio(include_hits, include_total),
        "must_exclude_precision": _ratio(exclude_hits, exclude_total),
        "boilerplate_leak_rate": round(1.0 - _ratio(exclude_hits, exclude_total), 4),
        "title_accuracy": _ratio(title_hits, title_total),
        "quality_status_accuracy": _ratio(status_hits, status_total),
        "runtime_mean_ms": round(statistics.fmean(runtimes), 3) if runtimes else 0.0,
        "runtime_p95_ms": round(sorted_runtimes[p95_index], 3) if sorted_runtimes else 0.0,
    }
    return {"version": "web-clean-eval-v1", "metrics": metrics, "results": results}


def evaluate_jsonl(path: str | Path) -> dict[str, Any]:
    return evaluate_rows(load_jsonl(path), dataset_path=path)
