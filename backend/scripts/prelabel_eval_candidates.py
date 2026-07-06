#!/usr/bin/env python3
"""Add review suggestions to offline-eval candidates without setting labels.

The T0.1 gate still requires human-reviewed ``label`` values. This helper
reduces the manual pass from "blank page for 500 rows" to "confirm or fix a
suggestion with a reason", while keeping validation honest: suggested fields
are ignored by ``validate_eval_set.py`` until a human writes ``label``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)

from scripts.run_offline_eval import VALID_LABELS

SUGGESTION_SOURCE = "heuristic-v1"
SUGGESTED_LABELS = VALID_LABELS

_NOISE_RE = re.compile(
    r"\b("
    r"deal|deals|discount|coupon|promo|sponsored|giveaway|sale|shopping|"
    r"roundup|liveblog|live blog|photo gallery|gallery|slideshow|"
    r"newsletter|subscribe|webinar|event registration"
    r")\b",
    re.IGNORECASE,
)
_MUST_SEE_RE = re.compile(
    r"\b("
    r"breaking|exclusive|investigation|lawsuit|ban|sanction|regulator|"
    r"central bank|fed|sec|fda|supreme court|parliament|congress|"
    r"openai|anthropic|deepmind|nvidia|semiconductor|ipo|acquisition|"
    r"security vulnerability|zero[- ]day|breach|ransomware"
    r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Suggestion:
    label: str
    confidence: float
    reason: str
    review_priority: str


def _score(record: dict[str, Any]) -> float | None:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    for key in ("final_score", "article_score", "score"):
        value = record.get(key, metadata.get(key))
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _text(record: dict[str, Any]) -> str:
    return " ".join(
        str(record.get(key) or "")
        for key in ("title", "summary", "full_content", "source_name", "source_type")
    )


def suggest_label(record: dict[str, Any]) -> Suggestion:
    """Return a transparent heuristic suggestion for a candidate record."""
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    text = _text(record)
    score = _score(record)
    full_content = str(record.get("full_content") or "").strip()
    summary = str(record.get("summary") or "").strip()
    source_metadata = record.get("source_metadata") if isinstance(record.get("source_metadata"), dict) else {}
    authority_type = str(source_metadata.get("authority_type") or "").strip().lower()

    if record.get("is_duplicate_of") or record.get("duplicate_of") or metadata.get("duplicate_group_id"):
        return Suggestion("noise", 0.9, "duplicate marker present", "low")

    fulltext_status = str(metadata.get("fulltext_status") or "").strip().lower()
    if fulltext_status == "title_only" and (score is None or score < 55):
        return Suggestion("noise", 0.82, "title-only item with low score", "medium")

    if _NOISE_RE.search(text) and (score is None or score < 70):
        return Suggestion("noise", 0.78, "commerce/promo/listing wording", "medium")

    if score is not None and score >= 88:
        return Suggestion("must_see", 0.82, f"very high score ({score:g})", "high")

    if _MUST_SEE_RE.search(text) and (score is None or score >= 60):
        confidence = 0.78 if score is None else min(0.86, 0.72 + (score / 1000.0))
        return Suggestion("must_see", round(confidence, 2), "high-signal topic/source wording", "high")

    if authority_type in {"regulator", "official"} and (summary or full_content):
        return Suggestion("ok", 0.76, f"authoritative source ({authority_type})", "medium")

    if score is not None and score >= 55:
        return Suggestion("ok", 0.7, f"moderate score ({score:g})", "medium")

    if not summary and len(full_content) < 120:
        return Suggestion("noise", 0.72, "thin text and no summary", "medium")

    return Suggestion("ok", 0.55, "default borderline content", "high")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            try:
                record = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"{path}:{line_no}: record must be a JSON object")
            records.append(record)
    return records


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def prelabel_records(
    records: list[dict[str, Any]],
    *,
    overwrite_suggestions: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    out: list[dict[str, Any]] = []
    label_counts: Counter[str] = Counter()
    priority_counts: Counter[str] = Counter()
    already_labeled = 0

    for record in records:
        item = dict(record)
        if str(item.get("label") or "").strip():
            already_labeled += 1
        existing = str(item.get("suggested_label") or "").strip()
        if existing and not overwrite_suggestions:
            if existing in SUGGESTED_LABELS:
                label_counts[existing] += 1
            priority_counts[str(item.get("review_priority") or "unknown")] += 1
            out.append(item)
            continue

        suggestion = suggest_label(item)
        item["suggested_label"] = suggestion.label
        item["suggested_confidence"] = suggestion.confidence
        item["suggested_reason"] = suggestion.reason
        item["suggested_label_source"] = SUGGESTION_SOURCE
        item["review_priority"] = suggestion.review_priority
        label_counts[suggestion.label] += 1
        priority_counts[suggestion.review_priority] += 1
        out.append(item)

    stats = {
        "records": len(out),
        "already_labeled": already_labeled,
        "suggested_labels": dict(sorted(label_counts.items())),
        "review_priority": dict(sorted(priority_counts.items())),
    }
    return out, stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Suggest labels for eval candidates without setting final labels")
    parser.add_argument("input", type=Path, help="Candidate JSONL from export_eval_candidates.py")
    parser.add_argument("--output", type=Path, required=True, help="Output JSONL with suggested_* fields")
    parser.add_argument(
        "--overwrite-suggestions",
        action="store_true",
        help="Replace existing suggested_* fields instead of preserving them",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable stats")
    args = parser.parse_args()

    records = _load_jsonl(args.input)
    labeled, stats = prelabel_records(records, overwrite_suggestions=args.overwrite_suggestions)
    _write_jsonl(args.output, labeled)

    payload = {"input": str(args.input), "output": str(args.output), **stats}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"prelabeled {stats['records']} eval candidates -> {args.output}")
        print(f"  already_labeled: {stats['already_labeled']}")
        print(f"  suggested_labels: {stats['suggested_labels']}")
        print(f"  review_priority: {stats['review_priority']}")
        print("  note: final label remains unchanged; run validate_eval_set.py after human review")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
