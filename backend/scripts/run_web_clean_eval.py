#!/usr/bin/env python3
"""Run deterministic Web Clean fixture evaluation with a fail-closed gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.domains.fetch.web_clean.eval import evaluate_jsonl


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Web Clean evaluation")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--tier", choices=("web_clean_bootstrap", "web_clean_eval_1_0"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--enforce", action="store_true")
    args = parser.parse_args()
    report = evaluate_jsonl(args.dataset, manifest_path=args.manifest, tier=args.tier)
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 1 if args.enforce and not report["ok"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
