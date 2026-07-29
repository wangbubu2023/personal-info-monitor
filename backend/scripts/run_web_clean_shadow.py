#!/usr/bin/env python3
"""Aggregate privacy-bounded Web Clean shadow observations.

The input is JSONL produced by an explicitly separate collection/export step.
This script never fetches URLs, reads credentials, or mutates Content rows.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.domains.fetch.web_clean.provenance import (
    PROVENANCE_GENERATOR,
    PROVENANCE_SCHEMA,
    verify_shadow_provenance,
)

_ALLOWED_DATASET_KINDS = {"local_fixture", "staging_shadow", "production_shadow"}
_HIGH_RISK_REASONS = {
    "new_empty",
    "severe_length_loss",
    "blocked_missed",
    "quality_regression",
    "timeout",
}
_SENSITIVE_KEYS = {
    "authorization",
    "body",
    "canonical_url",
    "content",
    "cookie",
    "cookies",
    "full_content",
    "headers",
    "html",
    "raw_html",
    "summary",
    "text",
    "title",
    "token",
    "url",
}
_SAFE_SCALAR_KEYS = {
    "observed_at",
    "old_text_chars",
    "new_text_chars",
    "old_quality_status",
    "new_quality_status",
    "expected_blocked",
    "new_blocked",
    "timeout",
    "production_affected",
    "risk_reason",
    "review_verdict",
    "extraction_method",
    "template_id",
    "quality_score",
}


def _utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


def _opaque(value: Any, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()[:20]


def _safe_sample(row: dict[str, Any], *, salt: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in row.items():
        normalized = str(key).lower()
        if normalized in _SENSITIVE_KEYS or any(
            marker in normalized for marker in ("secret", "password", "api_key")
        ):
            continue
        if normalized.endswith("_id") or normalized == "id":
            result[key] = _opaque(value, salt)
        elif normalized in _SAFE_SCALAR_KEYS and (
            isinstance(value, (str, int, float, bool)) or value is None
        ):
            if isinstance(value, float) and not math.isfinite(value):
                continue
            result[key] = str(value)[:160] if isinstance(value, str) else value
    return result


def _non_negative_int(value: Any) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("shadow character counts must be integers") from exc
    return max(0, parsed)


def _provenance_valid(
    provenance: dict[str, Any] | None,
    *,
    dataset_kind: str,
    input_sha256: str | None,
    provenance_hmac_key: str | None = None,
) -> bool:
    if not isinstance(provenance, dict) or not input_sha256:
        return False
    return (
        provenance.get("schema_version") == PROVENANCE_SCHEMA
        and provenance.get("generated_by") == PROVENANCE_GENERATOR
        and provenance.get("dataset_kind") == dataset_kind == "production_shadow"
        and provenance.get("observations_sha256") == input_sha256
        and verify_shadow_provenance(provenance, key=provenance_hmac_key)
    )


def _risk_reason(row: dict[str, Any]) -> str | None:
    explicit = str(row.get("risk_reason") or "").strip()
    if explicit in _HIGH_RISK_REASONS:
        return explicit
    old_chars = _non_negative_int(row.get("old_text_chars"))
    new_chars = _non_negative_int(row.get("new_text_chars"))
    expected_blocked = bool(row.get("expected_blocked"))
    detected_blocked = bool(row.get("new_blocked"))
    if bool(row.get("timeout")):
        return "timeout"
    if old_chars >= 200 and new_chars == 0:
        return "new_empty"
    if old_chars >= 500 and new_chars < old_chars * 0.35:
        return "severe_length_loss"
    if expected_blocked and not detected_blocked:
        return "blocked_missed"
    if str(row.get("old_quality_status") or "") in {"good", "full"} and str(
        row.get("new_quality_status") or ""
    ) in {"poor", "empty", "blocked"}:
        return "quality_regression"
    return None


def _longest_consecutive_days(days: set[str]) -> int:
    ordered = sorted(datetime.fromisoformat(day).date() for day in days)
    longest = current = 0
    previous = None
    for day in ordered:
        current = current + 1 if previous and day == previous + timedelta(days=1) else 1
        longest = max(longest, current)
        previous = day
    return longest


def build_web_clean_shadow_report(
    observations: list[dict[str, Any]],
    *,
    salt: str,
    dataset_kind: str,
    retention_days: int = 30,
    high_risk_limit: int = 50,
    provenance: dict[str, Any] | None = None,
    input_sha256: str | None = None,
    provenance_hmac_key: str | None = None,
) -> dict[str, Any]:
    """Build a non-authoritative report from already-collected shadow observations."""
    if dataset_kind not in _ALLOWED_DATASET_KINDS:
        raise ValueError(f"dataset_kind must be one of {sorted(_ALLOWED_DATASET_KINDS)}")
    if retention_days <= 0:
        raise ValueError("retention_days must be positive")
    if high_risk_limit <= 0:
        raise ValueError("high_risk_limit must be positive")

    observed_days: set[str] = set()
    total_old_chars = 0
    total_new_chars = 0
    changed = 0
    new_empty = 0
    timeouts = 0
    shadow_violations = 0
    high_risk_samples: list[dict[str, Any]] = []
    total_high_risk = 0
    reviewed = 0

    for row in observations:
        if not isinstance(row, dict):
            raise ValueError("each observation must be an object")
        observed_at = _utc(row["observed_at"])
        observed_days.add(observed_at.date().isoformat())
        old_chars = _non_negative_int(row.get("old_text_chars"))
        new_chars = _non_negative_int(row.get("new_text_chars"))
        total_old_chars += old_chars
        total_new_chars += new_chars
        changed += int(old_chars != new_chars or row.get("old_quality_status") != row.get("new_quality_status"))
        new_empty += int(old_chars > 0 and new_chars == 0)
        timeouts += int(bool(row.get("timeout")))
        shadow_violations += int(row.get("production_affected") is not False)
        reason = _risk_reason(row)
        if reason:
            total_high_risk += 1
            reviewed += int(bool(str(row.get("review_verdict") or "").strip()))
            if len(high_risk_samples) < high_risk_limit:
                sample = dict(row)
                sample["risk_reason"] = reason
                high_risk_samples.append(_safe_sample(sample, salt=salt))
    consecutive_days = _longest_consecutive_days(observed_days)
    count = len(observations)
    isolation_ok = shadow_violations == 0
    provenance_valid = _provenance_valid(
        provenance,
        dataset_kind=dataset_kind,
        input_sha256=input_sha256,
        provenance_hmac_key=provenance_hmac_key,
    )
    return {
        "schema_version": "web-clean-shadow-v1",
        "dataset_kind": dataset_kind,
        "shadow_only": isolation_ok,
        "production_affected": not isolation_ok,
        "provenance": {
            "valid": provenance_valid,
            "input_sha256": input_sha256,
            "schema_version": (
                str(provenance.get("schema_version") or "")[:80]
                if isinstance(provenance, dict)
                else None
            ),
            "generated_by": str(provenance.get("generated_by") or "")[:80] if isinstance(provenance, dict) else None,
            "dataset_kind": str(provenance.get("dataset_kind") or "")[:80] if isinstance(provenance, dict) else None,
            "observations_sha256": (
                str(provenance.get("observations_sha256") or "")[:64]
                if isinstance(provenance, dict)
                else None
            ),
            "generated_at": str(provenance.get("generated_at") or "")[:80] if isinstance(provenance, dict) else None,
            "attestation_hmac_sha256": (
                str(provenance.get("attestation_hmac_sha256") or "")[:64]
                if isinstance(provenance, dict)
                else None
            ),
        },
        "retention": {
            "days": retention_days,
            "delete_after": (datetime.now(timezone.utc) + timedelta(days=retention_days)).isoformat(),
            "content_policy": (
                "opaque ids and scalar diagnostics only; URLs, HTML, bodies, "
                "headers and credentials removed"
            ),
        },
        "window": {
            "first_day": min(observed_days) if observed_days else None,
            "last_day": max(observed_days) if observed_days else None,
            "observed_days": len(observed_days),
            "consecutive_days": consecutive_days,
            "minimum_days_met": consecutive_days >= 7,
        },
        "observations": {
            "count": count,
            "changed": changed,
            "changed_rate": round(changed / max(1, count), 6),
            "old_text_chars": total_old_chars,
            "new_text_chars": total_new_chars,
            "new_to_old_char_ratio": round(total_new_chars / max(1, total_old_chars), 6),
            "new_empty_count": new_empty,
            "timeout_count": timeouts,
            "shadow_isolation_violations": shadow_violations,
        },
        "high_risk_review": {
            "total_count": total_high_risk,
            "sample_count": len(high_risk_samples),
            "reviewed_count": reviewed,
            "samples": high_risk_samples,
        },
        "release_eligible": dataset_kind == "production_shadow"
        and provenance_valid
        and consecutive_days >= 7
        and isolation_ok
        and reviewed == total_high_risk,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate privacy-bounded Web Clean shadow report")
    parser.add_argument("snapshots", type=Path, help="JSONL scalar observations from a separate Shadow export")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--salt", required=True, help="Non-secret run salt used to pseudonymize identifiers")
    parser.add_argument("--dataset-kind", choices=sorted(_ALLOWED_DATASET_KINDS), required=True)
    parser.add_argument(
        "--provenance-manifest",
        type=Path,
        help="Production export attestation; required for a release-eligible production_shadow report",
    )
    parser.add_argument("--retention-days", type=int, default=30)
    parser.add_argument("--high-risk-limit", type=int, default=50)
    args = parser.parse_args()

    snapshot_bytes = args.snapshots.read_bytes()
    rows = [
        json.loads(line)
        for line in snapshot_bytes.decode("utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    provenance = None
    if args.provenance_manifest:
        provenance = json.loads(args.provenance_manifest.read_text(encoding="utf-8"))
        if not isinstance(provenance, dict):
            raise ValueError("provenance manifest must be a JSON object")
    report = build_web_clean_shadow_report(
        rows,
        salt=args.salt,
        dataset_kind=args.dataset_kind,
        retention_days=args.retention_days,
        high_risk_limit=args.high_risk_limit,
        provenance=provenance,
        input_sha256=hashlib.sha256(snapshot_bytes).hexdigest(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
