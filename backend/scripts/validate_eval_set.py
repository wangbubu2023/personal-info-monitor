#!/usr/bin/env python3
"""Validate and optionally install a manually labeled offline eval set."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)

from dotenv import load_dotenv

load_dotenv(os.path.join(backend_dir, ".env"))

from scripts.run_offline_eval import DEFAULT_EVAL_SET, VALID_LABELS, compute_metrics

DEFAULT_MIN_RECORDS = 500
DEFAULT_MIN_SOURCES = 20


@dataclass(frozen=True)
class EvalSetValidationResult:
    records: list[dict[str, Any]]
    errors: list[str]
    metrics: dict[str, Any]

    @property
    def ok(self) -> bool:
        return not self.errors


def _load_jsonl_with_lines(path: Path) -> list[tuple[int, dict[str, Any]]]:
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


def _source_key(record: dict[str, Any]) -> str:
    return str(record.get("source_id") or record.get("source_url") or record.get("source_name") or "").strip()


def validate_eval_set(
    path: Path,
    *,
    min_records: int = DEFAULT_MIN_RECORDS,
    min_sources: int = DEFAULT_MIN_SOURCES,
) -> EvalSetValidationResult:
    rows = _load_jsonl_with_lines(path)
    records = [record for _, record in rows]
    errors: list[str] = []

    if len(records) < min_records:
        errors.append(f"expected at least {min_records} records, found {len(records)}")

    seen_ids: dict[str, int] = {}
    sources: set[str] = set()
    for line_no, record in rows:
        record_id = str(record.get("id") or "").strip()
        if not record_id:
            errors.append(f"line {line_no}: id is required")
        elif record_id in seen_ids:
            errors.append(f"line {line_no}: duplicate id {record_id!r}; first seen on line {seen_ids[record_id]}")
        else:
            seen_ids[record_id] = line_no

        label = str(record.get("label") or "").strip()
        if not label:
            errors.append(f"line {line_no}: label is required")
        elif label not in VALID_LABELS:
            errors.append(f"line {line_no}: label must be one of {sorted(VALID_LABELS)}")

        title = str(record.get("title") or "").strip()
        url = str(record.get("url") or record.get("original_url") or "").strip()
        if not title:
            errors.append(f"line {line_no}: title is required")
        if not url:
            errors.append(f"line {line_no}: url is required")

        source_key = _source_key(record)
        if source_key:
            sources.add(source_key)

    if len(sources) < min_sources:
        errors.append(f"expected at least {min_sources} sources, found {len(sources)}")

    metrics = compute_metrics(records) if records and not any("label" in error for error in errors) else {}
    return EvalSetValidationResult(records=records, errors=errors, metrics=metrics)


def install_eval_set(records: list[dict[str, Any]], output: Path = DEFAULT_EVAL_SET) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a manually labeled PIM offline eval JSONL set")
    parser.add_argument("input", type=Path, help="Annotated JSONL file to validate")
    parser.add_argument("--min-records", type=int, default=DEFAULT_MIN_RECORDS)
    parser.add_argument("--min-sources", type=int, default=DEFAULT_MIN_SOURCES)
    parser.add_argument("--install", action="store_true", help="Install the validated set as tests/fixtures/eval_set.jsonl")
    parser.add_argument("--output", type=Path, default=DEFAULT_EVAL_SET, help="Install destination")
    parser.add_argument("--backup-existing", action="store_true", help="Copy an existing output file to .bak first")
    parser.add_argument("--max-errors", type=int, default=50, help="Maximum validation errors to print")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable validation result")
    args = parser.parse_args()

    result = validate_eval_set(args.input, min_records=args.min_records, min_sources=args.min_sources)
    visible_errors = result.errors[: max(0, args.max_errors)]
    payload = {
        "ok": result.ok,
        "input": str(args.input),
        "records": len(result.records),
        "error_count": len(result.errors),
        "errors": visible_errors,
        "errors_truncated": len(visible_errors) < len(result.errors),
        "metrics": result.metrics,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        status = "ok" if result.ok else "failed"
        print(f"eval_set validation {status}: {args.input}")
        print(f"  records: {len(result.records)}")
        for key, value in sorted(result.metrics.items()):
            print(f"  {key}: {value}")
        for error in visible_errors:
            print(f"  error: {error}", file=sys.stderr)
        hidden_errors = len(result.errors) - len(visible_errors)
        if hidden_errors > 0:
            print(f"  ... {hidden_errors} more errors hidden; use --max-errors to show more", file=sys.stderr)

    if not result.ok:
        return 1

    if args.install:
        if args.backup_existing and args.output.exists():
            shutil.copy2(args.output, args.output.with_suffix(args.output.suffix + ".bak"))
        install_eval_set(result.records, args.output)
        if not args.json:
            print(f"installed eval set -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
