#!/usr/bin/env python3
"""Fail CI when production BLE001 findings exceed the committed budget."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUDGET_FILE = Path(__file__).with_name("ble001_budget.json")
DEFAULT_APP_PATH = PROJECT_ROOT / "app"
RUFF_FAILURE_WITH_FINDINGS = 1


@dataclass(frozen=True)
class Ble001Violation:
    filename: str
    row: int
    message: str


@dataclass(frozen=True)
class BudgetResult:
    current_total: int
    max_total: int

    @property
    def ok(self) -> bool:
        return self.current_total <= self.max_total

    @property
    def remaining(self) -> int:
        return self.max_total - self.current_total


def load_budget(path: Path) -> int:
    data = json.loads(path.read_text())
    max_total = data.get("max_total")
    if not isinstance(max_total, int) or max_total < 0:
        raise ValueError(f"{path} must contain a non-negative integer max_total")
    return max_total


def _relative_filename(filename: str, project_root: Path) -> str:
    path = Path(filename)
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def parse_ruff_json(payload: str, project_root: Path = PROJECT_ROOT) -> list[Ble001Violation]:
    raw_items = json.loads(payload or "[]")
    violations: list[Ble001Violation] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        location = item.get("location") or {}
        row = location.get("row", 0) if isinstance(location, dict) else 0
        violations.append(
            Ble001Violation(
                filename=_relative_filename(str(item.get("filename", "")), project_root),
                row=int(row or 0),
                message=str(item.get("message", "")),
            )
        )
    return violations


def run_ruff_ble001(app_path: Path, project_root: Path = PROJECT_ROOT) -> list[Ble001Violation]:
    command = [
        sys.executable,
        "-m",
        "ruff",
        "check",
        "--select",
        "BLE001",
        "--ignore-noqa",
        "--isolated",
        "--output-format=json",
        str(app_path),
    ]
    completed = subprocess.run(command, cwd=project_root, capture_output=True, text=True, check=False)
    if completed.returncode not in (0, RUFF_FAILURE_WITH_FINDINGS):
        stderr = completed.stderr.strip()
        raise RuntimeError(f"ruff BLE001 check failed with exit code {completed.returncode}: {stderr}")
    return parse_ruff_json(completed.stdout, project_root)


def check_budget(violations: Sequence[Ble001Violation], max_total: int) -> BudgetResult:
    return BudgetResult(current_total=len(violations), max_total=max_total)


def format_top_files(violations: Sequence[Ble001Violation], limit: int = 10) -> str:
    counts = Counter(violation.filename for violation in violations)
    if not counts:
        return ""
    lines = [f"  {count:3} {filename}" for filename, count in counts.most_common(limit)]
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget-file", type=Path, default=DEFAULT_BUDGET_FILE)
    parser.add_argument("--app-path", type=Path, default=DEFAULT_APP_PATH)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    max_total = load_budget(args.budget_file)
    violations = run_ruff_ble001(args.app_path)
    result = check_budget(violations, max_total)

    if result.ok:
        print(f"BLE001 budget OK: {result.current_total} <= {result.max_total}")
        if result.remaining > 0:
            print(f"Budget can be lowered by {result.remaining}.")
        return 0

    print(f"BLE001 budget exceeded: {result.current_total} > {result.max_total}", file=sys.stderr)
    top_files = format_top_files(violations)
    if top_files:
        print("Top BLE001 files:", file=sys.stderr)
        print(top_files, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
