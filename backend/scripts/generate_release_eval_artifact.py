#!/usr/bin/env python3
"""Build a reproducible M2 release artifact and explicit Go/No-Go decision."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
DEFAULT_LOCK = ROOT / "uv.lock"
DEFAULT_CONFIG = ROOT / "scripts" / "formal_eval_config.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_commit() -> str:
    return subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _load(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def build_release_artifact(
    formal: dict[str, Any] | None,
    shadow: dict[str, Any] | None,
    *,
    config_path: Path,
    lock_path: Path,
    performance: dict[str, Any] | None = None,
    approvers: list[str] | None = None,
    commit: str | None = None,
) -> dict[str, Any]:
    blockers: list[str] = []
    config = json.loads(config_path.read_text(encoding="utf-8"))
    event_config = config.get("event") or {}
    shadow_config = config.get("shadow") or {}
    if not formal or not formal.get("ok"):
        blockers.append("formal Core/Event Eval 1.0 is missing or failed")
    if formal and formal.get("dataset_tier") != "formal_eval_1_0":
        blockers.append("dataset tier is not formal_eval_1_0")
    core = (formal or {}).get("core") or {}
    event = (formal or {}).get("event") or {}
    event_metrics = event.get("metrics") or {}
    pairwise = event_metrics.get("pairwise") or {}
    if core.get("record_count", 0) < 200:
        blockers.append("Core Eval has fewer than 200 records")
    if event.get("pair_count", 0) < 200:
        blockers.append("Event Eval has fewer than 200 pairs")
    precision_min = float(event_config.get("pair_precision_min", 0.92))
    recall_min = float(event_config.get("pair_recall_min", 0.82))
    wrong_merge_max = float(event_config.get("wrong_merge_rate_max_exclusive", 0.03))
    missing_merge_max = float(event_config.get("missing_merge_rate_max_exclusive", 0.08))
    if event_metrics:
        if pairwise.get("precision", 0) < precision_min:
            blockers.append(f"Event pair precision is below {precision_min}")
        if pairwise.get("recall", 0) < recall_min:
            blockers.append(f"Event pair recall is below {recall_min}")
        if event_metrics.get("wrong_merge_rate", 1) >= wrong_merge_max:
            blockers.append(f"wrong merge rate is not below {wrong_merge_max}")
        if event_metrics.get("missing_merge_rate", 1) >= missing_merge_max:
            blockers.append(f"missing merge rate is not below {missing_merge_max}")
    if not shadow:
        blockers.append("quality shadow report is missing")
    else:
        if shadow.get("production_affected") is not False or shadow.get("shadow_only") is not True:
            blockers.append("shadow isolation contract failed")
        minimum_shadow_days = int(shadow_config.get("minimum_days", 7))
        if shadow.get("window", {}).get("observed_days", 0) < minimum_shadow_days:
            blockers.append(f"Shadow window is shorter than {minimum_shadow_days} days")
        if shadow.get("high_risk_review", {}).get("sample_count", 0) > shadow.get(
            "high_risk_review", {}
        ).get("reviewed_count", 0):
            blockers.append("high-risk Shadow samples remain unreviewed")
    if not performance:
        blockers.append("performance baseline is missing")
    if not approvers:
        blockers.append("release approver is missing")

    known_failures = {
        "core": ((core.get("metrics") or {}).get("known_failures") or []),
        "event": (event_metrics.get("known_failures") or []),
    }
    return {
        "schema_version": "pim-release-eval-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provenance": {
            "commit": commit or _git_commit(),
            "config": str(config_path),
            "config_sha256": _sha256(config_path),
            "lock": str(lock_path),
            "lock_sha256": _sha256(lock_path),
            "core_dataset_sha256": core.get("dataset_sha256"),
            "event_dataset_sha256": event.get("dataset_sha256"),
            "dataset_tier": (formal or {}).get("dataset_tier"),
        },
        "core_eval": core,
        "event_eval": event,
        "ranking": ((core.get("metrics") or {}).get("ranking")),
        "calibration": ((core.get("metrics") or {}).get("calibration")),
        "production_diff": (formal or {}).get("production_diff"),
        "shadow_diff": shadow,
        "performance_baseline": performance,
        "known_failures": known_failures,
        "decision": {
            "result": "GO" if not blockers else "NO_GO",
            "blockers": blockers,
            "approvers": approvers or [],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate PIM release eval artifact")
    parser.add_argument("--formal-report", type=Path)
    parser.add_argument("--shadow-report", type=Path)
    parser.add_argument("--performance", type=Path)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--approver", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--enforce", action="store_true", help="Exit non-zero on NO_GO")
    args = parser.parse_args()
    artifact = build_release_artifact(
        _load(args.formal_report),
        _load(args.shadow_report),
        config_path=args.config,
        lock_path=args.lock,
        performance=_load(args.performance),
        approvers=args.approver,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if args.enforce and artifact["decision"]["result"] != "GO" else 0


if __name__ == "__main__":
    raise SystemExit(main())
