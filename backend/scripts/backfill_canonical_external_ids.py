#!/usr/bin/env python3
"""Backfill canonical article identity metadata for historical content rows.

Default mode is dry-run. Use ``--commit`` to persist changes.

Usage::

    cd backend
    .venv/bin/python scripts/backfill_canonical_external_ids.py
    .venv/bin/python scripts/backfill_canonical_external_ids.py --commit --days 30
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from datetime import timedelta

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)

from dotenv import load_dotenv

load_dotenv(os.path.join(backend_dir, ".env"))

from app.database import SessionLocal
from app.models import Content
from app.pipeline.utils import normalize_external_id
from app.utils.datetime import utcnow_naive
from app.utils.url import canonical_article_external_id


def _looks_like_url(value: str | None) -> bool:
    return str(value or "").strip().lower().startswith(("http://", "https://"))


def _canonical_identity_for_row(content: Content) -> str:
    for candidate in (content.original_url, content.external_id):
        canonical = canonical_article_external_id(candidate)
        if canonical and _looks_like_url(candidate):
            return canonical
    return ""


def _external_id_update_for_row(content: Content) -> str | None:
    if not _looks_like_url(content.external_id):
        return None
    normalized = normalize_external_id(content.external_id)
    if normalized and normalized != content.external_id:
        return normalized
    return None


def backfill_canonical_external_ids(
    *,
    db=None,
    dry_run: bool = True,
    days: int | None = 30,
    limit: int | None = None,
) -> dict[str, int]:
    owns_session = db is None
    db = db or SessionLocal()
    stats: Counter[str] = Counter()
    try:
        query = db.query(Content).order_by(Content.fetched_at.desc())
        if days is not None:
            cutoff = utcnow_naive() - timedelta(days=days)
            query = query.filter(Content.fetched_at >= cutoff)
        if limit is not None:
            query = query.limit(limit)

        for content in query.all():
            stats["total"] += 1
            meta = dict(content.metadata_ or {})
            canonical_identity = _canonical_identity_for_row(content)
            new_external_id = _external_id_update_for_row(content)

            changed = False
            if canonical_identity and meta.get("canonical_external_id") != canonical_identity:
                meta["canonical_external_id"] = canonical_identity
                changed = True
                stats["metadata_updated"] += 1

            if new_external_id:
                conflict = (
                    db.query(Content.id)
                    .filter(
                        Content.source_id == content.source_id,
                        Content.external_id == new_external_id,
                        Content.id != content.id,
                    )
                    .first()
                )
                if conflict:
                    stats["external_id_conflict"] += 1
                    meta["canonical_external_id_conflict"] = new_external_id
                    changed = True
                else:
                    meta.setdefault("previous_external_id", content.external_id)
                    content.external_id = new_external_id
                    changed = True
                    stats["external_id_updated"] += 1

            if changed:
                content.metadata_ = meta
            else:
                stats["unchanged"] += 1

        if dry_run:
            db.rollback()
        else:
            db.commit()
        return dict(stats)
    finally:
        if owns_session:
            db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill canonical external IDs for historical contents")
    parser.add_argument("--commit", action="store_true", help="Persist changes; defaults to dry-run")
    parser.add_argument("--days", type=int, default=30, help="Only scan rows fetched in the last N days")
    parser.add_argument("--all", action="store_true", help="Scan all rows instead of applying --days")
    parser.add_argument("--limit", type=int, default=None, help="Max rows to process")
    args = parser.parse_args()

    stats = backfill_canonical_external_ids(
        dry_run=not args.commit,
        days=None if args.all else args.days,
        limit=args.limit,
    )
    mode = "committed" if args.commit else "dry-run"
    print(f"backfill_canonical_external_ids ({mode}):")
    for key in sorted(stats):
        print(f"  {key}: {stats[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
