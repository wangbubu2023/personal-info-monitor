#!/usr/bin/env python3
"""Build a reproducible release artifact and explicit fail-closed decision."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.domains.fetch.web_clean.provenance import (
    PROVENANCE_KEY_ENV,
    verify_shadow_provenance,
)

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


def _web_clean_blockers(
    report: dict[str, Any] | None,
    shadow: dict[str, Any] | None,
    config: dict[str, Any],
    provenance_hmac_key: str | None = None,
) -> list[str]:
    blockers: list[str] = []
    metrics = (report or {}).get("metrics") or {}
    if not report or not report.get("ok"):
        blockers.append("formal Web Clean Eval 1.0 is missing or failed")
    if report and report.get("version") != "web-clean-eval-v2":
        blockers.append("Web Clean report version is not web-clean-eval-v2")
    if report and (report.get("gate") or {}).get("result") != "GO":
        blockers.append("Web Clean report gate is not GO")
    if report and report.get("dataset_tier") != "web_clean_eval_1_0":
        blockers.append("Web Clean dataset tier is not web_clean_eval_1_0")
    if report and report.get("manifest_valid") is not True:
        blockers.append("Web Clean manifest is missing or invalid")
    if report and not report.get("dataset_sha256"):
        blockers.append("Web Clean dataset hash is missing")
    if report and not report.get("manifest_sha256"):
        blockers.append("Web Clean manifest hash is missing")

    minimum_samples = int(config.get("minimum_samples", 150))
    if metrics.get("sample_count", 0) < minimum_samples:
        blockers.append(f"Web Clean Eval has fewer than {minimum_samples} samples")
    if metrics:
        labels = metrics.get("label_counts") or {}
        required_labels = (
            "must_include",
            "must_exclude",
            "title",
            "canonical_url",
            "published_time",
            "quality_status",
            "markdown",
        )
        for label in required_labels:
            if labels.get(label, 0) <= 0:
                blockers.append(f"Web Clean Eval has no {label} labels")
        if metrics.get("runtime_p95_ms", 0) <= 0:
            blockers.append("Web Clean runtime_p95_ms is missing or invalid")
        include_min = float(config.get("must_include_recall_min", 0.90))
        exclude_min = float(config.get("must_exclude_precision_min", 0.92))
        leak_max = float(config.get("boilerplate_leak_rate_max", 0.08))
        blocked_f1_min = float(config.get("blocked_detection_f1_min", 0.88))
        metadata_min = float(config.get("metadata_accuracy_min", 0.90))
        markdown_min = float(config.get("markdown_structure_score_min", 0.85))
        if metrics.get("must_include_recall", 0) < include_min:
            blockers.append(f"Web Clean must_include_recall is below {include_min}")
        if metrics.get("must_exclude_precision", 0) < exclude_min:
            blockers.append(f"Web Clean must_exclude_precision is below {exclude_min}")
        if metrics.get("boilerplate_leak_rate", 1) > leak_max:
            blockers.append(f"Web Clean boilerplate_leak_rate exceeds {leak_max}")
        if metrics.get("blocked_detection_f1", 0) < blocked_f1_min:
            blockers.append(f"Web Clean blocked_detection_f1 is below {blocked_f1_min}")
        if metrics.get("metadata_accuracy", 0) < metadata_min:
            blockers.append(f"Web Clean metadata_accuracy is below {metadata_min}")
        if metrics.get("markdown_structure_score", 0) < markdown_min:
            blockers.append(f"Web Clean markdown_structure_score is below {markdown_min}")

    if not shadow:
        blockers.append("Web Clean 7-day Shadow report is missing")
    else:
        if shadow.get("schema_version") != "web-clean-shadow-v1":
            blockers.append("Web Clean Shadow report version is not web-clean-shadow-v1")
        if shadow.get("dataset_kind") != "production_shadow":
            blockers.append("Web Clean Shadow is not marked as a production-shadow export")
        provenance = shadow.get("provenance") or {}
        input_sha256 = str(provenance.get("input_sha256") or "")
        observations_sha256 = str(provenance.get("observations_sha256") or "")
        if (
            not input_sha256
            or input_sha256 != observations_sha256
            or not verify_shadow_provenance(provenance, key=provenance_hmac_key)
        ):
            blockers.append("Web Clean Shadow production provenance is missing or invalid")
        if shadow.get("production_affected") is not False or shadow.get("shadow_only") is not True:
            blockers.append("Web Clean Shadow isolation contract failed")
        if (shadow.get("observations") or {}).get("shadow_isolation_violations", 0) != 0:
            blockers.append("Web Clean Shadow contains production-affecting observations")
        minimum_days = int(config.get("minimum_shadow_days", 7))
        if shadow.get("window", {}).get("consecutive_days", 0) < minimum_days:
            blockers.append(f"Web Clean Shadow continuous window is shorter than {minimum_days} days")
        review = shadow.get("high_risk_review") or {}
        if review.get("total_count", review.get("sample_count", 0)) > review.get("reviewed_count", 0):
            blockers.append("high-risk Web Clean Shadow samples remain unreviewed")
        if shadow.get("release_eligible") is not True:
            blockers.append("Web Clean Shadow report is not release-eligible")
    return blockers


def build_release_artifact(
    formal: dict[str, Any] | None,
    shadow: dict[str, Any] | None,
    *,
    config_path: Path,
    lock_path: Path,
    performance: dict[str, Any] | None = None,
    web_clean: dict[str, Any] | None = None,
    web_clean_shadow: dict[str, Any] | None = None,
    approvers: list[str] | None = None,
    commit: str | None = None,
    web_clean_provenance_hmac_key: str | None = None,
) -> dict[str, Any]:
    blockers: list[str] = []
    config = json.loads(config_path.read_text(encoding="utf-8"))
    event_config = config.get("event") or {}
    shadow_config = config.get("shadow") or {}
    web_clean_config = config.get("web_clean") or {}
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
    blockers.extend(
        _web_clean_blockers(
            web_clean,
            web_clean_shadow,
            web_clean_config,
            web_clean_provenance_hmac_key,
        )
    )
    if not performance:
        blockers.append("performance baseline is missing")
    if not approvers:
        blockers.append("release approver is missing")

    known_failures = {
        "core": ((core.get("metrics") or {}).get("known_failures") or []),
        "event": (event_metrics.get("known_failures") or []),
        "web_clean": ((web_clean or {}).get("known_failures") or []),
    }
    return {
        "schema_version": "pim-release-eval-v2",
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
            "web_clean_dataset_sha256": (web_clean or {}).get("dataset_sha256"),
            "web_clean_manifest_sha256": (web_clean or {}).get("manifest_sha256"),
            "web_clean_dataset_tier": (web_clean or {}).get("dataset_tier"),
        },
        "core_eval": core,
        "event_eval": event,
        "web_clean_eval": web_clean,
        "ranking": ((core.get("metrics") or {}).get("ranking")),
        "calibration": ((core.get("metrics") or {}).get("calibration")),
        "production_diff": (formal or {}).get("production_diff"),
        "shadow_diff": shadow,
        "web_clean_shadow": web_clean_shadow,
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
    parser.add_argument("--web-clean-report", type=Path)
    parser.add_argument("--web-clean-shadow-report", type=Path)
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
        web_clean=_load(args.web_clean_report),
        web_clean_shadow=_load(args.web_clean_shadow_report),
        approvers=args.approver,
        web_clean_provenance_hmac_key=os.getenv(PROVENANCE_KEY_ENV),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if args.enforce and artifact["decision"]["result"] != "GO" else 0


if __name__ == "__main__":
    raise SystemExit(main())
