#!/usr/bin/env python3
"""Gate offline eval history for enough runs and non-regressing precision."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)

from scripts.run_offline_eval import DEFAULT_HISTORY

CompareMode = Literal["previous", "first"]


@dataclass(frozen=True)
class EvalHistoryCheck:
    ok: bool
    history_points: int
    metric: str
    latest_value: float | None
    baseline_value: float | None
    compare_to: CompareMode
    max_drop: float
    errors: list[str]


def _load_history(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_no}: history row must be a JSON object")
            rows.append(row)
    return rows


def _metric_value(row: dict[str, Any], metric: str) -> float | None:
    metrics = row.get("metrics")
    if not isinstance(metrics, dict):
        return None
    value = metrics.get(metric)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def check_eval_history(
    history_path: Path = DEFAULT_HISTORY,
    *,
    min_points: int = 4,
    metric: str = "precision@20",
    compare_to: CompareMode = "previous",
    max_drop: float = 0.0,
) -> EvalHistoryCheck:
    rows = _load_history(history_path)
    errors: list[str] = []
    if len(rows) < min_points:
        errors.append(f"history has {len(rows)} point(s), expected at least {min_points}")

    latest_value: float | None = None
    baseline_value: float | None = None
    if rows:
        latest_value = _metric_value(rows[-1], metric)
        if latest_value is None:
            errors.append(f"latest history point is missing numeric metric {metric}")

    if compare_to == "previous":
        if len(rows) >= 2:
            baseline_value = _metric_value(rows[-2], metric)
            if baseline_value is None:
                errors.append(f"previous history point is missing numeric metric {metric}")
        else:
            errors.append("at least 2 history points are required for previous comparison")
    elif compare_to == "first":
        if rows:
            baseline_value = _metric_value(rows[0], metric)
            if baseline_value is None:
                errors.append(f"first history point is missing numeric metric {metric}")
    else:
        raise ValueError(f"unsupported compare mode: {compare_to}")

    if latest_value is not None and baseline_value is not None and latest_value + max_drop < baseline_value:
        errors.append(
            f"{metric} regressed: latest={latest_value:.4f}, "
            f"{compare_to}={baseline_value:.4f}, max_drop={max_drop:.4f}"
        )

    return EvalHistoryCheck(
        ok=not errors,
        history_points=len(rows),
        metric=metric,
        latest_value=latest_value,
        baseline_value=baseline_value,
        compare_to=compare_to,
        max_drop=max_drop,
        errors=errors,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail when offline eval history is insufficient or regresses")
    parser.add_argument("--history-path", type=Path, default=DEFAULT_HISTORY)
    parser.add_argument("--min-points", type=int, default=4)
    parser.add_argument("--metric", default="precision@20")
    parser.add_argument("--compare-to", choices=["previous", "first"], default="previous")
    parser.add_argument("--max-drop", type=float, default=0.0)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args()

    result = check_eval_history(
        args.history_path,
        min_points=args.min_points,
        metric=args.metric,
        compare_to=args.compare_to,
        max_drop=args.max_drop,
    )
    payload = asdict(result)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    elif result.ok:
        print(
            f"offline eval history gate passed: "
            f"{result.history_points} point(s), {result.metric}={result.latest_value}"
        )
    else:
        print("offline eval history gate failed:")
        for error in result.errors:
            print(f"  {error}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
