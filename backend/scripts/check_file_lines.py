#!/usr/bin/env python3
"""Fail CI when a budgeted file grows beyond its committed line-count baseline.

Same only-decrease policy as ``check_dead_code.py`` / ``check_ble001_budget.py``:
the budget file pins each oversized file at its current line count. New lines
cannot land in these files; every touch should shrink them ("one-touch rule":
whoever opens one of these files for a bugfix carves out the piece they touched).

Rationale (2026-07-07 review): four ~1000+ line files carry most of the
single-maintainer complexity tax. Dedicated refactor sprints contradict the
front-half feature freeze, so instead the gate blocks further growth and lets
routine maintenance push the numbers down over time.

Usage:
    python scripts/check_file_lines.py            # gate against budget
    python scripts/check_file_lines.py --update   # lower budgets to current counts
    python scripts/check_file_lines.py --list     # print current vs budget
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BUDGET_FILE = Path(__file__).with_name("file_lines_budget.json")


def count_lines(path: Path) -> int:
    with path.open("rb") as fh:
        return sum(1 for _ in fh)


def load_budget(budget_file: Path = DEFAULT_BUDGET_FILE) -> dict[str, int]:
    data = json.loads(budget_file.read_text(encoding="utf-8"))
    return {str(k): int(v) for k, v in data["max_lines"].items()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true", help="lower budgets to current line counts")
    parser.add_argument("--list", action="store_true", help="print current counts vs budget")
    args = parser.parse_args()

    budget = load_budget()
    current: dict[str, int] = {}
    missing: list[str] = []
    for rel_path in budget:
        path = REPO_ROOT / rel_path
        if not path.exists():
            missing.append(rel_path)
            continue
        current[rel_path] = count_lines(path)

    if missing:
        # A budgeted file disappearing is a win (it was split/deleted); the
        # budget entry should be removed in the same change.
        print(f"budgeted files no longer exist, remove them from the budget: {missing}")
        return 1

    if args.list:
        for rel_path, limit in sorted(budget.items()):
            print(f"{current[rel_path]:>6} / {limit:<6} {rel_path}")
        return 0

    if args.update:
        new_budget = {rel_path: min(limit, current[rel_path]) for rel_path, limit in budget.items()}
        DEFAULT_BUDGET_FILE.write_text(
            json.dumps({"max_lines": new_budget}, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"budget updated: {new_budget}")
        return 0

    failures = [
        f"{rel_path}: {current[rel_path]} lines > budget {limit} (only-decrease; split what you touched)"
        for rel_path, limit in budget.items()
        if current[rel_path] > limit
    ]
    if failures:
        print("file line budget exceeded:")
        for line in failures:
            print(f"  {line}")
        print("run scripts/check_file_lines.py --list for the full picture.")
        return 1

    lowered = [rel_path for rel_path, limit in budget.items() if current[rel_path] < limit]
    if lowered:
        print(f"budget can be lowered for {lowered}; run with --update and commit.")
    print("file line budgets OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
