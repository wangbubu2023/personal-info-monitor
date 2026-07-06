#!/usr/bin/env python3
"""Fail CI when vulture dead-code findings exceed the committed budget.

Same only-decrease policy as ``check_ble001_budget.py``: the budget file
pins the current finding count; new dead code cannot land, and every
cleanup should lower ``max_total``.

Rationale (2026-07-05 remediation audit): the codebase has had both
failure modes of dead code — "built but never wired" (session_health
before it was connected) and "unwired but never deleted" (rss.py page
hydration helpers after hydration moved to ingest finish). A budget gate
makes invariant 5 ("no write points without read points") machine-checked
instead of a documentation promise.

Vulture at 60% confidence is noisy (pydantic ``model_config``, callback
signatures), but the budget model tolerates noise: false positives are
frozen into the budget once and only deltas matter.

Usage:
    python scripts/check_dead_code.py            # gate against budget
    python scripts/check_dead_code.py --update   # rewrite budget to current count
    python scripts/check_dead_code.py --list     # print findings
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUDGET_FILE = Path(__file__).with_name("dead_code_budget.json")
DEFAULT_APP_PATH = PROJECT_ROOT / "app"
MIN_CONFIDENCE = 60


def run_vulture(app_path: Path = DEFAULT_APP_PATH) -> list[str]:
    """Run vulture and return finding lines (excludes __pycache__)."""
    proc = subprocess.run(  # noqa: S603 - fixed argv, no user input
        [
            sys.executable,
            "-m",
            "vulture",
            str(app_path),
            "--min-confidence",
            str(MIN_CONFIDENCE),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    # vulture exits 3 when findings exist; 0 when clean; 1 on invalid input.
    if proc.returncode not in (0, 3):
        raise RuntimeError(f"vulture failed (exit {proc.returncode}): {proc.stderr.strip()[:500]}")
    return [
        line
        for line in proc.stdout.splitlines()
        if line.strip() and "__pycache__" not in line
    ]


def load_budget(path: Path) -> int:
    data = json.loads(path.read_text())
    max_total = data.get("max_total")
    if not isinstance(max_total, int) or max_total < 0:
        raise ValueError(f"{path} must contain a non-negative integer max_total")
    return max_total


def write_budget(path: Path, total: int) -> None:
    path.write_text(
        json.dumps({"max_total": total, "min_confidence": MIN_CONFIDENCE}, indent=2) + "\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget-file", type=Path, default=DEFAULT_BUDGET_FILE)
    parser.add_argument("--app-path", type=Path, default=DEFAULT_APP_PATH)
    parser.add_argument("--update", action="store_true", help="rewrite budget to current count")
    parser.add_argument("--list", action="store_true", help="print all findings")
    args = parser.parse_args(argv)

    findings = run_vulture(args.app_path)
    total = len(findings)

    if args.list:
        for line in findings:
            print(line)

    if args.update:
        write_budget(args.budget_file, total)
        print(f"dead-code budget updated: max_total={total}")
        return 0

    max_total = load_budget(args.budget_file)
    if total > max_total:
        print(f"FAIL: {total} vulture findings > budget {max_total}.")
        print("New dead code is not allowed. Either delete/wire the code, or if this")
        print("is a confirmed false positive, run with --update and justify the bump")
        print("in the commit message. Run with --list to see findings.")
        return 1

    print(f"OK: {total} vulture findings within budget {max_total} (headroom {max_total - total}).")
    if total < max_total:
        print(f"Consider lowering the budget to {total} in {args.budget_file.name}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
