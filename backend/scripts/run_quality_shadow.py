#!/usr/bin/env python3
"""Generate a privacy-bounded score/Event/Today shadow diff report."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SENSITIVE_KEYS = {
    "authorization",
    "body",
    "content",
    "cookie",
    "cookies",
    "full_content",
    "headers",
    "note",
    "summary",
    "text",
    "title",
    "token",
    "url",
}


def _utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


def _opaque(value: Any, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()[:20]


def _sanitize(value: Any, *, salt: str, parent_key: str = "") -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            normalized = str(key).lower()
            if normalized in SENSITIVE_KEYS or any(marker in normalized for marker in ("secret", "password", "api_key")):
                continue
            if normalized.endswith("_id") or normalized == "id":
                result[key] = _opaque(item, salt)
            else:
                result[key] = _sanitize(item, salt=salt, parent_key=normalized)
        return result
    if isinstance(value, list):
        return [_sanitize(item, salt=salt, parent_key=parent_key) for item in value]
    return value


def build_shadow_report(
    snapshots: list[dict[str, Any]],
    *,
    salt: str,
    retention_days: int = 30,
    high_risk_limit: int = 50,
) -> dict[str, Any]:
    """Aggregate immutable shadow observations without changing production state."""

    if retention_days <= 0:
        raise ValueError("retention_days must be positive")
    score_rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []
    today_rows: list[dict[str, Any]] = []
    observed_days: set[str] = set()
    for snapshot in snapshots:
        observed_at = _utc(snapshot["observed_at"])
        observed_days.add(observed_at.date().isoformat())
        score_rows.extend(snapshot.get("score_diffs") or [])
        event_rows.extend(snapshot.get("event_diffs") or [])
        today_rows.extend(snapshot.get("today_diffs") or [])

    score_changed = [
        row for row in score_rows if float(row.get("old_score") or 0) != float(row.get("new_score") or 0)
    ]
    event_changed = [
        row
        for row in event_rows
        if row.get("old_event_id") != row.get("new_event_id") or row.get("old_decision") != row.get("new_decision")
    ]
    today_changed = [
        row
        for row in today_rows
        if row.get("old_rank") != row.get("new_rank") or bool(row.get("old_selected")) != bool(row.get("new_selected"))
    ]
    assignment_rows = [row for row in event_rows if row.get("old_event_id") is not None]
    id_churn = sum(row.get("old_event_id") != row.get("new_event_id") for row in assignment_rows) / max(
        1, len(assignment_rows)
    )
    wrong_merge = [row for row in event_rows if row.get("review_verdict") == "wrong_merge"]
    missing_merge = [row for row in event_rows if row.get("review_verdict") == "missing_merge"]
    reviewed = [row for row in event_rows if row.get("review_verdict") in {"correct", "wrong_merge", "missing_merge"}]
    risk_order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    high_risk = sorted(
        [row for row in event_changed + today_changed if risk_order.get(str(row.get("risk") or "").lower(), 0) >= 3],
        key=lambda row: risk_order.get(str(row.get("risk") or "").lower(), 0),
        reverse=True,
    )[:high_risk_limit]
    sanitized_samples = _sanitize(high_risk, salt=salt)
    return {
        "schema_version": "quality-shadow-v1",
        "shadow_only": True,
        "production_affected": False,
        "retention": {
            "days": retention_days,
            "delete_after": (datetime.now(timezone.utc) + timedelta(days=retention_days)).isoformat(),
            "content_policy": "opaque ids and structured diffs only; text, URLs, credentials, and bodies removed",
        },
        "window": {
            "first_day": min(observed_days) if observed_days else None,
            "last_day": max(observed_days) if observed_days else None,
            "observed_days": len(observed_days),
            "minimum_days_met": len(observed_days) >= 7,
            "recommended_days_met": len(observed_days) >= 14,
        },
        "score": {
            "observations": len(score_rows),
            "changed": len(score_changed),
            "changed_rate": round(len(score_changed) / max(1, len(score_rows)), 6),
        },
        "event": {
            "observations": len(event_rows),
            "changed": len(event_changed),
            "changed_rate": round(len(event_changed) / max(1, len(event_rows)), 6),
            "id_churn": round(id_churn, 6),
            "reviewed": len(reviewed),
            "wrong_merge_rate": round(len(wrong_merge) / max(1, len(reviewed)), 6),
            "missing_merge_rate": round(len(missing_merge) / max(1, len(reviewed)), 6),
        },
        "today": {
            "observations": len(today_rows),
            "changed": len(today_changed),
            "changed_rate": round(len(today_changed) / max(1, len(today_rows)), 6),
        },
        "high_risk_review": {
            "sample_count": len(sanitized_samples),
            "reviewed_count": sum(1 for row in high_risk if row.get("review_verdict")),
            "samples": sanitized_samples,
        },
    }


def prune_expired_shadow_reports(directory: Path, *, now: datetime | None = None) -> list[str]:
    """Delete only expired JSON reports under the explicitly supplied directory."""

    removed: list[str] = []
    current = now or datetime.now(timezone.utc)
    if not directory.exists():
        return removed
    for path in directory.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            delete_after = payload.get("retention", {}).get("delete_after")
            if delete_after and _utc(delete_after) <= current:
                path.unlink()
                removed.append(path.name)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate quality shadow diff report")
    parser.add_argument("snapshots", type=Path, help="JSONL snapshots from score/Event/Today parallel runs")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--salt", required=True, help="Non-secret run salt used to pseudonymize identifiers")
    parser.add_argument("--retention-days", type=int, default=30)
    parser.add_argument("--prune-directory", type=Path)
    args = parser.parse_args()
    rows = [
        json.loads(line)
        for line in args.snapshots.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    report = build_shadow_report(rows, salt=args.salt, retention_days=args.retention_days)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.prune_directory:
        report["pruned"] = prune_expired_shadow_reports(args.prune_directory)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
