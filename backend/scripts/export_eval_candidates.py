#!/usr/bin/env python3
"""Export recent production content as an offline-eval annotation candidate set."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)

from dotenv import load_dotenv
from sqlalchemy.orm import Session, joinedload

load_dotenv(os.path.join(backend_dir, ".env"))

from app.models.content import Content
from app.models.source import Source
from app.platform.persistence.database import SessionLocal
from app.utils.datetime import utcnow_naive
from scripts.run_offline_eval import VALID_LABELS

DEFAULT_OUTPUT = Path.home() / ".pim" / "data" / "eval_candidates.jsonl"
DEFAULT_LIMIT = 500
DEFAULT_DAYS = 30


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None).isoformat()
    return None


def _compact_text(value: str | None, max_chars: int) -> str:
    text = (value or "").strip()
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


def _score_value(content: Content, key: str) -> float | None:
    direct = getattr(content, key, None)
    if direct is not None:
        try:
            return float(direct)
        except (TypeError, ValueError):
            pass
    metadata = content.metadata_ if isinstance(content.metadata_, dict) else {}
    value = metadata.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _metadata_subset(metadata: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "article_fulltext",
        "fulltext_status",
        "duplicate_group_id",
        "fetch_acceptance",
        "fetch_incomplete_reason",
        "selection_status",
        "lane",
        "score_basis",
        "article_score",
        "final_score",
    )
    return {key: metadata[key] for key in keys if key in metadata}


def _source_metadata_subset(metadata: dict[str, Any]) -> dict[str, Any]:
    keys = ("authority_type", "source_stars", "source_weight", "domain_focus")
    return {key: metadata[key] for key in keys if key in metadata}


def content_to_eval_record(
    content: Content,
    *,
    default_label: str = "",
    max_full_content_chars: int = 4000,
    formal_dataset: bool = False,
) -> dict[str, Any]:
    source = content.source
    metadata = content.metadata_ if isinstance(content.metadata_, dict) else {}
    source_metadata = source.metadata_ if source is not None and isinstance(source.metadata_, dict) else {}
    article_score = _score_value(content, "article_score")
    final_score = _score_value(content, "final_score")
    source_type = source.type.value if source is not None and hasattr(source.type, "value") else str(source.type) if source else ""

    record: dict[str, Any] = {
        "id": str(content.id),
        "title": content.title or "",
        "summary": content.summary or "",
        "url": content.original_url or "",
        "publish_time": _iso(content.publish_time),
        "fetched_at": _iso(content.fetched_at),
        "created_at": _iso(content.created_at),
        "label": default_label,
        "full_content": _compact_text(content.full_content, max_full_content_chars),
        "content_type": content.content_type or "",
        "source_id": str(source.id) if source is not None else str(content.source_id or ""),
        "source_name": source.name if source is not None else "",
        "source_type": source_type,
        "source_url": source.url if source is not None else "",
        "metadata": _metadata_subset(metadata),
        "source_metadata": _source_metadata_subset(source_metadata),
        "annotation_notes": "",
    }
    if article_score is not None and not formal_dataset:
        record["article_score"] = article_score
    if final_score is not None and not formal_dataset:
        record["final_score"] = final_score
    duplicate_group_id = metadata.get("duplicate_group_id")
    if duplicate_group_id:
        record["duplicate_group_id"] = duplicate_group_id
    if formal_dataset:
        body_length = len((content.full_content or "").strip())
        record["strata"] = {
            "source_type": source_type or "unknown",
            "language": str(metadata.get("language") or metadata.get("detected_language") or "unknown"),
            "paywall": bool(
                metadata.get("paywall")
                or metadata.get("is_paywalled")
                or metadata.get("requires_subscription")
            ),
            "content_length": "short" if body_length < 500 else "medium" if body_length < 2000 else "long",
            "case_type": str(metadata.get("eval_case_type") or "normal"),
        }
    return record


def interleave_by_source(contents: Iterable[Content], *, limit: int) -> list[Content]:
    buckets: dict[str, deque[Content]] = defaultdict(deque)
    order: list[str] = []
    for content in contents:
        source_key = str(content.source_id or getattr(content.source, "id", None) or f"source-object:{id(content.source)}")
        if source_key not in buckets:
            order.append(source_key)
        buckets[source_key].append(content)

    selected: list[Content] = []
    while len(selected) < limit and order:
        next_order: list[str] = []
        for source_key in order:
            bucket = buckets[source_key]
            if not bucket:
                continue
            selected.append(bucket.popleft())
            if len(selected) >= limit:
                break
            if bucket:
                next_order.append(source_key)
        order = next_order
    return selected


def load_candidate_contents(
    db: Session,
    *,
    limit: int = DEFAULT_LIMIT,
    days: int = DEFAULT_DAYS,
    include_archived: bool = False,
    now: datetime | None = None,
) -> list[Content]:
    now = (now or utcnow_naive()).replace(tzinfo=None)
    cutoff = now - timedelta(days=days)
    query = (
        db.query(Content)
        .options(joinedload(Content.source))
        .join(Source, Content.source_id == Source.id)
        .filter(Content.created_at >= cutoff)
    )
    if not include_archived:
        query = query.filter(Content.archived.is_(False))
    query = query.order_by(Content.created_at.desc(), Content.id.desc()).limit(max(limit * 10, limit))
    return interleave_by_source(query.all(), limit=limit)


def load_candidate_contents_expanding(
    db: Session,
    *,
    limit: int = DEFAULT_LIMIT,
    days: int = DEFAULT_DAYS,
    min_records: int | None = None,
    expand_days_step: int = 30,
    max_days: int | None = None,
    include_archived: bool = False,
    now: datetime | None = None,
) -> tuple[list[Content], int]:
    """Load candidates, widening the time window until enough rows exist.

    T0.1 needs a stable 500-row labeling pool, but small local deployments can
    have fewer than 500 recent rows in the default 30-day window. This keeps the
    default recency bias while removing the manual guesswork of retrying
    ``--days 60``, ``--days 90``, and so on.
    """
    target = min_records if min_records and min_records > 0 else None
    current_days = max(1, int(days))
    step = max(1, int(expand_days_step))
    ceiling = max_days if max_days and max_days > 0 else current_days
    ceiling = max(current_days, int(ceiling))
    now_value = now or utcnow_naive()

    while True:
        contents = load_candidate_contents(
            db,
            limit=limit,
            days=current_days,
            include_archived=include_archived,
            now=now_value,
        )
        if not target or len(contents) >= target or current_days >= ceiling:
            return contents, current_days
        current_days = min(current_days + step, ceiling)


def export_eval_candidates(
    db: Session,
    *,
    output: Path,
    limit: int = DEFAULT_LIMIT,
    days: int = DEFAULT_DAYS,
    min_records: int | None = None,
    expand_days_step: int = 30,
    max_days: int | None = None,
    default_label: str = "",
    include_archived: bool = False,
    max_full_content_chars: int = 4000,
    formal_dataset: bool = False,
    now: datetime | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if default_label and default_label not in VALID_LABELS:
        raise ValueError(f"default_label must be blank or one of {sorted(VALID_LABELS)}")
    contents, effective_days = load_candidate_contents_expanding(
        db,
        limit=limit,
        days=days,
        min_records=min_records,
        expand_days_step=expand_days_step,
        max_days=max_days,
        include_archived=include_archived,
        now=now,
    )
    if diagnostics is not None:
        diagnostics["requested_days"] = days
        diagnostics["effective_days"] = effective_days
        diagnostics["min_records"] = min_records
        diagnostics["record_count"] = len(contents)
    records = [
        content_to_eval_record(
            content,
            default_label=default_label,
            max_full_content_chars=max_full_content_chars,
            formal_dataset=formal_dataset,
        )
        for content in contents
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="Export recent PIM contents for manual eval labeling")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument(
        "--min-records",
        type=int,
        default=None,
        help="If set, expand the date window until at least this many records are exported or --max-days is reached",
    )
    parser.add_argument("--expand-days-step", type=int, default=30)
    parser.add_argument("--max-days", type=int, default=None)
    parser.add_argument("--label", default="", help="Optional prefilled label: must_see, ok, or noise")
    parser.add_argument("--include-archived", action="store_true")
    parser.add_argument("--max-full-content-chars", type=int, default=4000)
    parser.add_argument(
        "--formal",
        action="store_true",
        help="Omit existing predictions and emit formal_eval_1_0 strata fields",
    )
    args = parser.parse_args()

    diagnostics: dict[str, Any] = {}
    with SessionLocal() as db:
        records = export_eval_candidates(
            db,
            output=args.output,
            limit=args.limit,
            days=args.days,
            min_records=args.min_records,
            expand_days_step=args.expand_days_step,
            max_days=args.max_days,
            default_label=args.label,
            include_archived=args.include_archived,
            max_full_content_chars=args.max_full_content_chars,
            formal_dataset=args.formal,
            diagnostics=diagnostics,
        )
    source_count = len({record.get("source_id") for record in records if record.get("source_id")})
    unlabeled = sum(1 for record in records if not record.get("label"))
    print(f"exported {len(records)} eval candidates from {source_count} sources -> {args.output}")
    if diagnostics.get("effective_days") != diagnostics.get("requested_days"):
        print(f"expanded candidate window to {diagnostics['effective_days']} days")
    if unlabeled:
        print("labels are blank; fill each label with one of: must_see, ok, noise")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
