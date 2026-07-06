#!/usr/bin/env python3
"""Gate offline eval metrics against checked-in regression thresholds."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)

from scripts.run_offline_eval import DEFAULT_EVAL_SET, run_offline_eval

DEFAULT_THRESHOLDS = Path(backend_dir) / "scripts" / "offline_eval_thresholds.json"


@dataclass(frozen=True)
class MetricViolation:
    metric: str
    actual: float
    expected: float
    direction: str


def _load_thresholds(path: Path) -> dict[str, dict[str, float]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: thresholds must be a JSON object")

    parsed: dict[str, dict[str, float]] = {"min": {}, "max": {}}
    for direction in ("min", "max"):
        raw = payload.get(direction, {})
        if not isinstance(raw, dict):
            raise ValueError(f"{path}: {direction} thresholds must be an object")
        for metric, value in raw.items():
            if not isinstance(metric, str) or not metric:
                raise ValueError(f"{path}: metric names must be non-empty strings")
            try:
                parsed[direction][metric] = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{path}: threshold for {metric} must be numeric") from exc
    return parsed


def check_metric_thresholds(
    metrics: dict[str, Any],
    thresholds: dict[str, dict[str, float]],
) -> list[MetricViolation]:
    violations: list[MetricViolation] = []
    for metric, expected in thresholds.get("min", {}).items():
        actual = metrics.get(metric)
        if actual is None:
            violations.append(MetricViolation(metric=metric, actual=float("nan"), expected=expected, direction="min"))
            continue
        actual_float = float(actual)
        if actual_float < expected:
            violations.append(MetricViolation(metric=metric, actual=actual_float, expected=expected, direction="min"))
    for metric, expected in thresholds.get("max", {}).items():
        actual = metrics.get(metric)
        if actual is None:
            violations.append(MetricViolation(metric=metric, actual=float("nan"), expected=expected, direction="max"))
            continue
        actual_float = float(actual)
        if actual_float > expected:
            violations.append(MetricViolation(metric=metric, actual=actual_float, expected=expected, direction="max"))
    return violations


def _format_violation(violation: MetricViolation) -> str:
    comparator = ">=" if violation.direction == "min" else "<="
    return f"{violation.metric}: actual={violation.actual} expected {comparator} {violation.expected}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail when offline eval metrics regress past thresholds")
    parser.add_argument("--eval-set", type=Path, default=DEFAULT_EVAL_SET)
    parser.add_argument("--thresholds", type=Path, default=DEFAULT_THRESHOLDS)
    args = parser.parse_args()

    thresholds = _load_thresholds(args.thresholds)
    result = run_offline_eval(args.eval_set, history_path=None, append_history=False)
    metrics = result["metrics"]
    violations = check_metric_thresholds(metrics, thresholds)
    if violations:
        print("offline eval regression detected:")
        for violation in violations:
            print(f"  {_format_violation(violation)}")
        return 1

    print("offline eval regression gate passed")
    for key in sorted(metrics):
        print(f"  {key}: {metrics[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
