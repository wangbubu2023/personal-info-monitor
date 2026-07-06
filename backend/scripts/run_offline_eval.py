#!/usr/bin/env python3
"""Run the PIM offline quality evaluation set.

Usage::

    cd backend
    .venv/bin/python scripts/run_offline_eval.py
    .venv/bin/python scripts/run_offline_eval.py --eval-set tests/fixtures/eval_set.jsonl --json
    .venv/bin/python scripts/run_offline_eval.py --no-history
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)

from dotenv import load_dotenv

load_dotenv(os.path.join(backend_dir, ".env"))

from app.domains.score.scoring import merge_baseline_scoring_metadata
from app.utils.url import normalize_host

DEFAULT_EVAL_SET = Path(backend_dir) / "tests" / "fixtures" / "eval_set.jsonl"
DEFAULT_HISTORY = Path.home() / ".pim" / "data" / "eval_history.jsonl"
RELEVANT_LABELS = {"must_see", "ok"}
VALID_LABELS = RELEVANT_LABELS | {"noise"}


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
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
            label = str(record.get("label") or "").strip()
            if label not in VALID_LABELS:
                raise ValueError(f"{path}:{line_no}: label must be one of {sorted(VALID_LABELS)}")
            records.append(record)
    return records


def _score_from_metadata(record: dict[str, Any]) -> float | None:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    for key in ("article_score", "final_score", "score"):
        value = record.get(key, metadata.get(key))
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None


def _score_record(record: dict[str, Any]) -> float:
    explicit = _score_from_metadata(record)
    if explicit is not None:
        return explicit
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    source_metadata = record.get("source_metadata") if isinstance(record.get("source_metadata"), dict) else {}
    scored = merge_baseline_scoring_metadata(
        metadata,
        title=str(record.get("title") or ""),
        summary=record.get("summary"),
        full_content=record.get("full_content"),
        source_metadata=source_metadata,
        content_type=str(record.get("content_type") or ""),
        content=None,
    )
    return float(scored.get("article_score") or scored.get("final_score") or 0.0)


def _top_records(records: list[dict[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
    return sorted(records, key=lambda item: (_score_record(item), str(item.get("id") or "")), reverse=True)[:limit]


def _source_key(record: dict[str, Any]) -> str:
    source_id = str(record.get("source_id") or "").strip()
    if source_id:
        return f"id:{source_id}"
    source_url = record.get("source_url") or record.get("url") or record.get("original_url")
    host = normalize_host(source_url)
    if host:
        return f"host:{host}"
    source_name = str(record.get("source_name") or "").strip().lower()
    return f"name:{source_name}" if source_name else ""


def _nearest_rank(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil((percentile / 100.0) * len(ordered)) - 1))
    return round(ordered[index], 2)


def _is_duplicate(record: dict[str, Any], seen_groups: set[str]) -> bool:
    duplicate_of = record.get("is_duplicate_of") or record.get("duplicate_of")
    if duplicate_of:
        return True
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    group_id = record.get("duplicate_group_id") or metadata.get("duplicate_group_id")
    if not group_id:
        return False
    group = str(group_id)
    if group in seen_groups:
        return True
    seen_groups.add(group)
    return False


def _fulltext_complete(record: dict[str, Any]) -> bool:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    if metadata.get("article_fulltext") or metadata.get("fulltext_status") == "full":
        return True
    return len(str(record.get("full_content") or "").strip()) >= 280


def _title_only(record: dict[str, Any]) -> bool:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    if metadata.get("fulltext_status") == "title_only":
        return True
    return not str(record.get("summary") or "").strip() and not str(record.get("full_content") or "").strip()


def compute_metrics(records: list[dict[str, Any]], *, top_k: int = 20) -> dict[str, Any]:
    total = len(records)
    if total == 0:
        return {
            "total": 0,
            "precision@20": None,
            "duplicate_rate": None,
            "freshness_lag_p50": None,
            "freshness_lag_p90": None,
            "fulltext_complete_rate": None,
            "title_only_rate": None,
            "source_diversity@20": 0,
            "source_coverage@20": None,
            "covered_sources@20": 0,
            "total_sources": 0,
        }

    top = _top_records(records, top_k)
    relevant = sum(1 for record in top if record.get("label") in RELEVANT_LABELS)
    seen_groups: set[str] = set()
    duplicates = sum(1 for record in records if _is_duplicate(record, seen_groups))
    lags = []
    for record in records:
        published = _parse_dt(record.get("publish_time"))
        fetched = _parse_dt(record.get("fetched_at") or record.get("created_at"))
        if published and fetched:
            lags.append(max(0.0, (fetched - published).total_seconds() / 60.0))

    all_sources = {_source_key(record) for record in records}
    all_sources.discard("")
    top_sources = {_source_key(record) for record in top}
    top_sources.discard("")

    return {
        "total": total,
        "precision@20": round(relevant / max(1, len(top)), 4),
        "duplicate_rate": round(duplicates / total, 4),
        "freshness_lag_p50": _nearest_rank(lags, 50),
        "freshness_lag_p90": _nearest_rank(lags, 90),
        "fulltext_complete_rate": round(sum(1 for item in records if _fulltext_complete(item)) / total, 4),
        "title_only_rate": round(sum(1 for item in records if _title_only(item)) / total, 4),
        "source_diversity@20": len(top_sources),
        "source_coverage@20": round(len(top_sources) / len(all_sources), 4) if all_sources else None,
        "covered_sources@20": len(top_sources),
        "total_sources": len(all_sources),
    }


def run_offline_eval(
    eval_set: Path = DEFAULT_EVAL_SET,
    *,
    history_path: Path | None = DEFAULT_HISTORY,
    append_history: bool = True,
) -> dict[str, Any]:
    records = _load_jsonl(eval_set)
    metrics = compute_metrics(records)
    result = {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "eval_set": str(eval_set),
        "metrics": metrics,
    }
    if append_history and history_path is not None:
        history_path.parent.mkdir(parents=True, exist_ok=True)
        with history_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run offline PIM eval metrics")
    parser.add_argument("--eval-set", type=Path, default=DEFAULT_EVAL_SET)
    parser.add_argument("--history-path", type=Path, default=DEFAULT_HISTORY)
    parser.add_argument("--no-history", action="store_true", help="Do not append to eval history")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args()

    result = run_offline_eval(
        args.eval_set,
        history_path=args.history_path,
        append_history=not args.no_history,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        metrics = result["metrics"]
        print(f"offline_eval: {result['eval_set']}")
        for key in sorted(metrics):
            print(f"  {key}: {metrics[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
