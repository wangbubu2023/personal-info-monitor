#!/usr/bin/env python3
"""Build runnable PIM eval datasets from the July 2026 human annotations.

The source assets stay immutable:

- ``~/.pim/data/eval/eval_set_v1_4_2026-07-06.jsonl``
- ``~/Downloads/eval_export_20260724_074010.zip``
- ``~/Desktop/labels/*.jsonl``

The script installs prediction-free Core Bootstrap/Formal fixtures and writes
auxiliary gold datasets plus review queues under ``~/.pim/data/eval/gold``.
Run without ``--apply`` to inspect the intended outputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit

backend_dir = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend_dir))

from app.domains.score.score_vocab import VALID_LANES
from app.domains.score.scoring import SCORE_VERSION
from scripts.check_bootstrap_eval import BOOTSTRAP_RELEASE_SCOPE
from scripts.check_core_eval_dataset import build_manifest
from scripts.run_formal_eval import FORMAL_RELEASE_SCOPE, FORMAL_TIER

DEFAULT_LEGACY_EVAL = Path.home() / ".pim" / "data" / "eval" / "eval_set_v1_4_2026-07-06.jsonl"
DEFAULT_EXPORT_ZIP = Path.home() / "Downloads" / "eval_export_20260724_074010.zip"
DEFAULT_LABELS_DIR = Path.home() / "Desktop" / "labels"
DEFAULT_FIXTURES_DIR = backend_dir / "tests" / "fixtures"
DEFAULT_GOLD_DIR = Path.home() / ".pim" / "data" / "eval" / "gold"

BOOTSTRAP_RECORDS = 100
MAX_BODY_CHARS = 4000
DECISIVE_EVENT_LABELS = {"correct", "partial", "incorrect"}
STABLE_LEGACY_LANES = {
    "corporate": "company_news",
    "markets": "markets",
    "regulation": "regulation",
}
LANE_NOTE_MAP = {
    "公司新闻corporate": "company_news",
    "产品新闻tech_product": "product_news",
    "other": "other",
    "markets": "markets",
    "市场新闻 market": "markets",
    "regulation": "regulation",
    "公共人物（待新建）": "public_figures",
    "macro_finance": "macro_finance",
    "geopolitics": "geopolitics",
    "vc_deals": "vc_deals",
}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            payload = json.loads(text)
            if not isinstance(payload, dict):
                raise ValueError(f"{path}:{line_no}: row must be an object")
            rows.append(payload)
    return rows


def _read_zip_jsonl(archive: zipfile.ZipFile, name: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with archive.open(name) as handle:
        for line_no, raw in enumerate(handle, start=1):
            text = raw.decode("utf-8").strip()
            if not text:
                continue
            payload = json.loads(text)
            if not isinstance(payload, dict):
                raise ValueError(f"{name}:{line_no}: row must be an object")
            rows.append(payload)
    return rows


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_id(namespace: str, value: Any) -> str:
    raw = f"{namespace}\0{value}".encode()
    return hashlib.sha256(raw).hexdigest()[:20]


def _clean_url(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parts = urlsplit(text)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _compact_text(value: Any, limit: int = MAX_BODY_CHARS) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _redact_text(value: str) -> str:
    value = re.sub(
        r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        "[EMAIL]",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)", "[PHONE]", value)
    value = re.sub(r"\bsk-[A-Za-z0-9_-]{16,}\b", "[TOKEN]", value)
    return value


def _language(title: str, summary: str) -> str:
    text = f"{title} {summary}"[:1200]
    cjk = sum(1 for char in text if "\u3400" <= char <= "\u9fff")
    latin = sum(1 for char in text if char.isascii() and char.isalpha())
    if cjk >= 8 and cjk >= latin * 0.18:
        return "zh"
    return "en"


def _paywall_stratum(source_name: str, source_url: str) -> str:
    corpus = f"{source_name} {source_url}".lower()
    markers = (
        "nytimes",
        "纽约时报",
        "wsj",
        "wall street journal",
        "ft.com",
        "financial times",
        "bloomberg",
        "economist",
        "technologyreview",
        "mit technology review",
    )
    return "known_or_likely_paywalled" if any(marker in corpus for marker in markers) else "not_observed"


def _content_length(body: str) -> str:
    length = len(body.strip())
    if length < 500:
        return "short"
    if length < 2000:
        return "medium"
    return "long"


def _case_type(record: dict[str, Any], metadata: dict[str, Any]) -> str:
    if record.get("duplicate_group_id") or metadata.get("duplicate_group_id"):
        return "near_duplicate"
    if metadata.get("fulltext_status") in {"title_only", "summary_only"}:
        return "limited_fulltext"
    if record.get("label") == "noise":
        return "low_signal"
    return "normal"


def _normalize_core_record(record: dict[str, Any], *, namespace: str) -> dict[str, Any]:
    metadata_raw = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    source_metadata_raw = (
        record.get("source_metadata") if isinstance(record.get("source_metadata"), dict) else {}
    )
    metadata_keys = (
        "article_fulltext",
        "fulltext_status",
        "duplicate_group_id",
        "fetch_acceptance",
        "fetch_incomplete_reason",
    )
    source_metadata_keys = ("authority_type", "source_stars", "source_weight", "domain_focus")
    metadata = {key: metadata_raw[key] for key in metadata_keys if key in metadata_raw}
    source_metadata = {
        key: source_metadata_raw[key] for key in source_metadata_keys if key in source_metadata_raw
    }
    title = str(record.get("title") or "").strip()
    summary = _redact_text(_compact_text(record.get("summary"), 2000))
    full_content = _redact_text(_compact_text(record.get("full_content")))
    source_name = str(record.get("source_name") or "").strip()
    source_url = _clean_url(record.get("source_url"))
    duplicate_group_id = record.get("duplicate_group_id") or metadata.get("duplicate_group_id")
    normalized: dict[str, Any] = {
        "id": _stable_id(namespace, record.get("id")),
        "title": title,
        "summary": summary,
        "full_content": full_content,
        "url": _clean_url(record.get("url") or record.get("original_url")),
        "label": str(record.get("label") or "").strip(),
        "label_source": str(record.get("label_source") or "human-review-sheet-v1").strip(),
        "annotation_notes": str(record.get("annotation_notes") or "").strip(),
        "content_type": str(record.get("content_type") or "").strip(),
        "publish_time": record.get("publish_time"),
        "fetched_at": record.get("fetched_at"),
        "source_id": _stable_id(f"{namespace}-source", record.get("source_id") or source_url or source_name),
        "source_name": source_name,
        "source_url": source_url,
        "metadata": metadata,
        "source_metadata": source_metadata,
        "strata": {
            "source_type": str(record.get("source_type") or record.get("content_type") or "unknown"),
            "language": _language(title, summary),
            "paywall": _paywall_stratum(source_name, source_url),
            "content_length": _content_length(full_content),
            "case_type": _case_type(record, metadata),
        },
    }
    if duplicate_group_id:
        normalized["duplicate_group_id"] = str(duplicate_group_id)
    return normalized


def _split_legacy_rows(
    rows: list[dict[str, Any]],
    *,
    bootstrap_count: int = BOOTSTRAP_RECORDS,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if len(rows) <= bootstrap_count:
        raise ValueError("legacy eval must leave records for the formal split")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("label") or "")].append(row)
    for label_rows in grouped.values():
        label_rows.sort(key=lambda row: _stable_id("core-split", row.get("id")))

    exact = {label: len(label_rows) * bootstrap_count / len(rows) for label, label_rows in grouped.items()}
    quotas = {label: math.floor(value) for label, value in exact.items()}
    remaining = bootstrap_count - sum(quotas.values())
    for label in sorted(grouped, key=lambda key: (exact[key] - quotas[key], key), reverse=True)[:remaining]:
        quotas[label] += 1

    bootstrap_ids: set[str] = set()
    for label, label_rows in grouped.items():
        bootstrap_ids.update(str(row.get("id")) for row in label_rows[: quotas[label]])
    bootstrap = [row for row in rows if str(row.get("id")) in bootstrap_ids]
    formal = [row for row in rows if str(row.get("id")) not in bootstrap_ids]
    return bootstrap, formal


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sampling_interval(rows: list[dict[str, Any]]) -> str:
    values = sorted(
        str(row.get("publish_time") or row.get("fetched_at") or "")
        for row in rows
        if row.get("publish_time") or row.get("fetched_at")
    )
    return f"{values[0]}/{values[-1]}" if values else "unknown"


def _git_commit() -> str:
    result = subprocess.run(
        ["git", "-C", str(backend_dir.parent), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _core_manifest(
    path: Path,
    rows: list[dict[str, Any]],
    *,
    dataset_tier: str,
    release_scope: str,
    source_dataset: Path,
    split_name: str,
) -> dict[str, Any]:
    manifest = build_manifest(path, rows)
    manifest.update(
        {
            "dataset_tier": dataset_tier,
            "release_scope": release_scope,
            "git_commit": _git_commit(),
            "config_version": SCORE_VERSION,
            "sampling_interval": _sampling_interval(rows),
            "sampling": {
                "method": "deterministic label-stratified split of a 500-row production review set",
                "source_dataset": source_dataset.name,
                "split": split_name,
                "disjoint_splits": True,
            },
            "deidentification": {
                "content_and_source_ids": "deterministic SHA-256 pseudonyms",
                "url_queries_and_fragments": "removed",
                "emails_phone_numbers_and_token_patterns": "redacted",
                "body_limit_chars": MAX_BODY_CHARS,
                "reviewed": True,
            },
            "annotation_policy": {
                "human_review_required": True,
                "suggested_labels_are_not_final": True,
                "valid_labels": ["must_see", "noise", "ok"],
                "source": "human-review-sheet-v1",
            },
            "annotators": ["shuhuaiwang"],
            "quality_checks": {
                "prediction_fields_removed": True,
                "source_dataset_sha256": _sha256_path(source_dataset),
                "split_overlap": 0,
            },
            "split_policy": {
                "bootstrap": "100-row label-stratified infrastructure gate",
                "formal": "remaining 400 rows, never used by the bootstrap fixture",
            },
            "limitations": [
                "Single-annotator labels; future difficult examples should be double-reviewed.",
                "Paywall stratum is source-level known/likely status because row-level paywall was unavailable.",
                "Public article text is truncated and URL query strings are removed.",
            ],
        }
    )
    return manifest


def _verify_label_keys(
    source_rows: list[dict[str, Any]],
    label_rows: list[dict[str, Any]],
    *,
    key: str,
    name: str,
) -> None:
    source_ids = {str(row.get(key) or "") for row in source_rows}
    label_ids = {str(row.get(key) or "") for row in label_rows}
    if source_ids != label_ids:
        missing = sorted(source_ids - label_ids)[:5]
        extra = sorted(label_ids - source_ids)[:5]
        raise ValueError(f"{name}: source/label key mismatch missing={missing} extra={extra}")


def _candidate_context(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "sample_id": row.get("sample_id"),
        "title": str(row.get("title") or ""),
        "summary": _compact_text(row.get("summary"), 2000),
        "content_excerpt": _compact_text(
            row.get("content_excerpt_short") or row.get("content_excerpt"),
            1600,
        ),
        "content_type": row.get("content_type"),
        "domain": row.get("domain"),
        "source_type": row.get("source_type"),
        "source_name": row.get("source_name"),
        "language": row.get("language"),
        "publish_time": row.get("publish_time"),
        "fetched_at": row.get("fetched_at"),
    }


def _consensus(values: Iterable[Any]) -> tuple[Any, list[Any]]:
    nonempty = [value for value in values if value not in (None, "")]
    unique = sorted(set(nonempty))
    if len(unique) == 1:
        return unique[0], []
    if len(unique) > 1:
        return None, unique
    return None, []


def _build_core_quality(
    bootstrap_rows: list[dict[str, Any]],
    formal_rows: list[dict[str, Any]],
    bootstrap_labels: list[dict[str, Any]],
    formal_labels: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {
        str(row["sample_id"]): row for row in [*bootstrap_rows, *formal_rows]
    }
    annotations: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in bootstrap_labels:
        annotations[str(row["sample_id"])].append({"tier": "bootstrap", **row})
    for row in formal_labels:
        annotations[str(row["sample_id"])].append({"tier": "formal", **row})

    rows: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    conflict_counts: Counter[str] = Counter()
    gold_counts: Counter[str] = Counter()
    for sample_id in sorted(candidates):
        source_annotations = annotations[sample_id]
        gold: dict[str, Any] = {}
        conflicts: dict[str, list[Any]] = {}
        for field in ("relevance", "quality", "fact_density", "lane_fit"):
            value, conflict = _consensus(annotation.get(field) for annotation in source_annotations)
            gold[field] = value
            if value is not None:
                gold_counts[field] += 1
            if conflict:
                conflicts[field] = conflict
                conflict_counts[field] += 1
        row = {
            **_candidate_context(candidates[sample_id]),
            "gold": gold,
            "conflicts": conflicts,
            "annotation_sources": [
                {
                    "tier": annotation["tier"],
                    "note": annotation.get("note"),
                    **{
                        field: annotation.get(field)
                        for field in ("relevance", "quality", "fact_density", "lane_fit")
                        if field in annotation
                    },
                }
                for annotation in source_annotations
            ],
            "label_source": "human-review-multidimension-v1",
        }
        rows.append(row)
        if conflicts:
            review.append(row)
    summary = {
        "record_count": len(rows),
        "gold_dimension_counts": dict(sorted(gold_counts.items())),
        "conflict_counts": dict(sorted(conflict_counts.items())),
        "review_queue_count": len(review),
    }
    return rows, review, summary


def _build_lane_eval(
    formal_rows: list[dict[str, Any]],
    formal_labels: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    candidates = {str(row["sample_id"]): row for row in formal_rows}
    gold_rows: list[dict[str, Any]] = []
    review_rows: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for label in formal_labels:
        sample_id = str(label["sample_id"])
        candidate = candidates[sample_id]
        lane_fit = label.get("lane_fit")
        legacy_lane = str(candidate.get("lane") or "")
        note = str(label.get("note") or "")
        gold_lane: str | None = None
        derivation = ""
        if lane_fit == "misfit" and note in LANE_NOTE_MAP:
            gold_lane = LANE_NOTE_MAP[note]
            derivation = "explicit human correction note"
        elif lane_fit == "fits" and legacy_lane in STABLE_LEGACY_LANES:
            gold_lane = STABLE_LEGACY_LANES[legacy_lane]
            derivation = "human fits judgment on an unambiguously renamed legacy lane"

        context = {
            **_candidate_context(candidate),
            "annotation_context": {
                "legacy_lane": legacy_lane,
                "lane_fit": lane_fit,
                "note": note or None,
            },
        }
        if gold_lane is None:
            review_rows.append(
                {
                    **context,
                    "review_reason": (
                        "new taxonomy split requires a direct 13-class label"
                        if lane_fit == "fits"
                        else "human correction note is ambiguous under the 13-class taxonomy"
                    ),
                    "allowed_lanes": sorted(VALID_LANES),
                    "gold_lane": None,
                }
            )
            continue
        counts[gold_lane] += 1
        gold_rows.append(
            {
                **context,
                "gold_lane": gold_lane,
                "label_source": "human-review-derived-lane-v1",
                "derivation": derivation,
            }
        )

    missing = sorted(set(VALID_LANES) - set(counts))
    summary = {
        "record_count": len(gold_rows),
        "review_queue_count": len(review_rows),
        "lane_counts": dict(sorted(counts.items())),
        "missing_lanes": missing,
    }
    return gold_rows, review_rows, summary


def _event_context(row: dict[str, Any]) -> dict[str, Any]:
    event = row.get("event") if isinstance(row.get("event"), dict) else {}
    members = row.get("members") if isinstance(row.get("members"), list) else []
    return {
        "pair_id": row.get("pair_id"),
        "event": {
            "title": str(event.get("title") or ""),
            "summary": _compact_text(event.get("summary"), 2400),
            "status": event.get("status"),
            "event_state": event.get("event_state"),
            "cluster_version": event.get("cluster_version"),
        },
        "members": [
            {
                "title": str(member.get("title") or ""),
                "summary": _compact_text(member.get("summary"), 1200),
                "source_name": member.get("source_name"),
                "source_type": member.get("source_type"),
                "publish_time": member.get("publish_time"),
                "role": member.get("role"),
            }
            for member in members
            if isinstance(member, dict)
        ],
    }


def _build_event_card_eval(
    bootstrap_rows: list[dict[str, Any]],
    formal_rows: list[dict[str, Any]],
    bootstrap_labels: list[dict[str, Any]],
    formal_labels: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    candidates = {str(row["pair_id"]): row for row in [*bootstrap_rows, *formal_rows]}
    annotations: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in bootstrap_labels:
        annotations[str(row["pair_id"])].append({"tier": "bootstrap", **row})
    for row in formal_labels:
        annotations[str(row["pair_id"])].append({"tier": "formal", **row})

    gold_rows: list[dict[str, Any]] = []
    review_rows: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    for pair_id in sorted(candidates):
        source_annotations = annotations[pair_id]
        label, conflicts = _consensus(
            annotation.get("event_correctness") for annotation in source_annotations
        )
        context = _event_context(candidates[pair_id])
        annotation_context = [
            {
                "tier": annotation["tier"],
                "event_correctness": annotation.get("event_correctness"),
                "note": annotation.get("note"),
            }
            for annotation in source_annotations
        ]
        if conflicts:
            reason = "conflicting_annotations"
        elif label == "unclear":
            reason = "unclear"
        elif label not in DECISIVE_EVENT_LABELS:
            reason = "unlabeled"
        else:
            reason = ""
        if reason:
            reasons[reason] += 1
            review_rows.append(
                {
                    **context,
                    "gold_event_correctness": None,
                    "review_reason": reason,
                    "annotation_candidates": conflicts,
                    "annotation_context": annotation_context,
                }
            )
            continue
        counts[str(label)] += 1
        gold_rows.append(
            {
                **context,
                "gold_event_correctness": label,
                "label_source": "human-review-event-card-v1",
                "annotation_context": annotation_context,
            }
        )
    summary = {
        "record_count": len(gold_rows),
        "review_queue_count": len(review_rows),
        "label_counts": dict(sorted(counts.items())),
        "review_reason_counts": dict(sorted(reasons.items())),
        "scope": "event card correctness only; not pairwise clustering or membership",
    }
    return gold_rows, review_rows, summary


def _aux_manifest(
    path: Path,
    *,
    dataset_type: str,
    summary: dict[str, Any],
    source_hashes: dict[str, str],
    limitations: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": "pim_aux_eval_manifest_v1",
        "dataset": path.name,
        "dataset_type": dataset_type,
        "dataset_sha256": _sha256_path(path),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(),
        "score_version": SCORE_VERSION,
        "annotators": ["shuhuaiwang"],
        "label_source": "human review",
        "summary": summary,
        "source_hashes": source_hashes,
        "limitations": limitations,
    }


def build_assets(
    *,
    legacy_eval: Path,
    export_zip: Path,
    labels_dir: Path,
    fixtures_dir: Path,
    gold_dir: Path,
    apply: bool,
) -> dict[str, Any]:
    for path in (legacy_eval, export_zip, labels_dir / "manifest.json"):
        if not path.exists():
            raise FileNotFoundError(path)

    legacy_rows = _read_jsonl(legacy_eval)
    if len(legacy_rows) != 500:
        raise ValueError(f"expected 500 legacy Core rows, found {len(legacy_rows)}")
    if {str(row.get("label_source") or "") for row in legacy_rows} != {
        "human-review-sheet-v1"
    }:
        raise ValueError("legacy Core rows are not uniformly human-reviewed")

    core_bootstrap_labels = _read_jsonl(labels_dir / "core_bootstrap_labels.jsonl")
    core_formal_labels = _read_jsonl(labels_dir / "core_eval_labels.jsonl")
    event_bootstrap_labels = _read_jsonl(labels_dir / "event_bootstrap_labels.jsonl")
    event_formal_labels = _read_jsonl(labels_dir / "event_eval_labels.jsonl")
    labels_manifest = json.loads((labels_dir / "manifest.json").read_text(encoding="utf-8"))

    with zipfile.ZipFile(export_zip) as archive:
        core_bootstrap_source = _read_zip_jsonl(archive, "core_bootstrap_v0_1.jsonl")
        core_formal_source = _read_zip_jsonl(archive, "core_eval_v1_0_candidates.jsonl")
        event_bootstrap_source = _read_zip_jsonl(archive, "event_bootstrap_v0_1.jsonl")
        event_formal_source = _read_zip_jsonl(archive, "event_eval_v1_0_candidates.jsonl")

    _verify_label_keys(
        core_bootstrap_source,
        core_bootstrap_labels,
        key="sample_id",
        name="core bootstrap",
    )
    _verify_label_keys(
        core_formal_source,
        core_formal_labels,
        key="sample_id",
        name="core formal",
    )
    _verify_label_keys(
        event_bootstrap_source,
        event_bootstrap_labels,
        key="pair_id",
        name="event bootstrap",
    )
    _verify_label_keys(
        event_formal_source,
        event_formal_labels,
        key="pair_id",
        name="event formal",
    )

    bootstrap_raw, formal_raw = _split_legacy_rows(legacy_rows)
    bootstrap_rows = sorted(
        (_normalize_core_record(row, namespace="core-bootstrap-v0.1") for row in bootstrap_raw),
        key=lambda row: row["id"],
    )
    formal_rows = sorted(
        (_normalize_core_record(row, namespace="core-formal-v1.0") for row in formal_raw),
        key=lambda row: row["id"],
    )

    core_bootstrap_path = fixtures_dir / "core_bootstrap_v0_1.jsonl"
    core_bootstrap_manifest_path = fixtures_dir / "core_bootstrap_v0_1_manifest.json"
    core_formal_path = fixtures_dir / "core_eval_1_0.jsonl"
    core_formal_manifest_path = fixtures_dir / "core_eval_1_0_manifest.json"

    core_quality_rows, core_quality_review, core_quality_summary = _build_core_quality(
        core_bootstrap_source,
        core_formal_source,
        core_bootstrap_labels,
        core_formal_labels,
    )
    lane_rows, lane_review, lane_summary = _build_lane_eval(
        core_formal_source,
        core_formal_labels,
    )
    event_rows, event_review, event_summary = _build_event_card_eval(
        event_bootstrap_source,
        event_formal_source,
        event_bootstrap_labels,
        event_formal_labels,
    )

    plan = {
        "mode": "apply" if apply else "dry-run",
        "inputs": {
            "legacy_eval": str(legacy_eval),
            "legacy_eval_sha256": _sha256_path(legacy_eval),
            "export_zip": str(export_zip),
            "export_zip_sha256": _sha256_path(export_zip),
            "labels_dir": str(labels_dir),
            "labels_manifest_schema": labels_manifest.get("schema_version"),
        },
        "core_bootstrap": {
            "dataset": str(core_bootstrap_path),
            "manifest": str(core_bootstrap_manifest_path),
            "records": len(bootstrap_rows),
        },
        "core_formal": {
            "dataset": str(core_formal_path),
            "manifest": str(core_formal_manifest_path),
            "records": len(formal_rows),
        },
        "core_quality": core_quality_summary,
        "lane_eval": lane_summary,
        "event_card_eval": event_summary,
        "pending": {
            "event_pair_bootstrap": "requires real two-content same/different-event pairs",
            "event_pair_formal": "requires >=50 gold clusters and >=200 pairs",
            "today_diff": "3 exported rows remain unreviewed and are too few",
            "lane_full_coverage": f"{len(lane_review)} rows need direct 13-class review",
            "title_rewrite": "no human title rewrite labels exist",
        },
    }
    if not apply:
        return plan

    _write_jsonl(core_bootstrap_path, bootstrap_rows)
    _write_jsonl(core_formal_path, formal_rows)
    _write_json(
        core_bootstrap_manifest_path,
        _core_manifest(
            core_bootstrap_path,
            bootstrap_rows,
            dataset_tier="bootstrap",
            release_scope=BOOTSTRAP_RELEASE_SCOPE,
            source_dataset=legacy_eval,
            split_name="bootstrap",
        ),
    )
    _write_json(
        core_formal_manifest_path,
        _core_manifest(
            core_formal_path,
            formal_rows,
            dataset_tier=FORMAL_TIER,
            release_scope=FORMAL_RELEASE_SCOPE,
            source_dataset=legacy_eval,
            split_name="formal",
        ),
    )

    review_dir = gold_dir / "review_queues"
    core_quality_path = gold_dir / "core_quality_v0_1.jsonl"
    lane_path = gold_dir / "lane_eval_v0_1.jsonl"
    event_path = gold_dir / "event_card_correctness_v0_1.jsonl"
    source_hashes = {
        "legacy_eval": _sha256_path(legacy_eval),
        "export_zip": _sha256_path(export_zip),
        "labels_manifest": _sha256_path(labels_dir / "manifest.json"),
    }

    _write_jsonl(core_quality_path, core_quality_rows)
    _write_jsonl(review_dir / "core_quality_adjudication_v0_1.jsonl", core_quality_review)
    _write_json(
        gold_dir / "core_quality_v0_1_manifest.json",
        _aux_manifest(
            core_quality_path,
            dataset_type="core_multidimensional_quality",
            summary=core_quality_summary,
            source_hashes=source_hashes,
            limitations=[
                "No automatic mapping to must_see/ok/noise; original human dimensions are preserved.",
                "Conflicting duplicate annotations remain null and are emitted to a review queue.",
            ],
        ),
    )

    _write_jsonl(lane_path, lane_rows)
    _write_jsonl(review_dir / "lane_eval_v0_1_needs_review.jsonl", lane_review)
    _write_json(
        gold_dir / "lane_eval_v0_1_manifest.json",
        _aux_manifest(
            lane_path,
            dataset_type="lane_classification_seed",
            summary=lane_summary,
            source_hashes=source_hashes,
            limitations=[
                "Seed set is derived only from explicit correction notes and stable legacy-lane fits.",
                "Rows affected by the 13-class taxonomy split remain in the review queue.",
            ],
        ),
    )

    _write_jsonl(event_path, event_rows)
    _write_jsonl(review_dir / "event_card_correctness_v0_1_needs_review.jsonl", event_review)
    _write_json(
        gold_dir / "event_card_correctness_v0_1_manifest.json",
        _aux_manifest(
            event_path,
            dataset_type="event_card_correctness",
            summary=event_summary,
            source_hashes=source_hashes,
            limitations=[
                "This dataset evaluates whether an Event card is valid, not pairwise clustering.",
                "Source export contains zero or one member per Event, so coherence/member-match are unavailable.",
            ],
        ),
    )

    _write_json(gold_dir / "eval_inventory_v0_1.json", plan)
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-eval", type=Path, default=DEFAULT_LEGACY_EVAL)
    parser.add_argument("--export-zip", type=Path, default=DEFAULT_EXPORT_ZIP)
    parser.add_argument("--labels-dir", type=Path, default=DEFAULT_LABELS_DIR)
    parser.add_argument("--fixtures-dir", type=Path, default=DEFAULT_FIXTURES_DIR)
    parser.add_argument("--gold-dir", type=Path, default=DEFAULT_GOLD_DIR)
    parser.add_argument("--apply", action="store_true", help="Write datasets; default is dry-run")
    args = parser.parse_args()
    result = build_assets(
        legacy_eval=args.legacy_eval,
        export_zip=args.export_zip,
        labels_dir=args.labels_dir,
        fixtures_dir=args.fixtures_dir,
        gold_dir=args.gold_dir,
        apply=args.apply,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
