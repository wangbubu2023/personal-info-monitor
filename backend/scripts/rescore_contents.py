#!/usr/bin/env python3
"""Batch re-score all contents with the current pim-score-v2 rules.

Clears cached score metadata, re-applies summary cleaning, and stamps fresh
``article_score`` / ``dimension_scores`` for rows that pass fetch acceptance.

Usage::

    cd backend
    .venv/bin/python scripts/rescore_contents.py
    .venv/bin/python scripts/rescore_contents.py --dry-run
    .venv/bin/python scripts/rescore_contents.py --limit 50
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)

from dotenv import load_dotenv

load_dotenv(os.path.join(backend_dir, ".env"))

from sqlalchemy.orm import joinedload

from app.database import SessionLocal
from app.domains.fetch.acceptance import (
    assess_fetch_acceptance,
    ensure_listing_summary,
    stamp_fetch_acceptance_metadata,
)
from app.domains.ingest.summary_clean import apply_summary_cleaning
from app.features import KEYWORD_MONITORING_ENABLED
from app.models import Content, Keyword
from app.processors.keyword_matcher import KeywordMatcher
from app.services.content_quality_service import merge_content_quality_metadata
from app.services.scoring_service import SCORE_VERSION, merge_baseline_scoring_metadata

_SCORE_CACHE_KEYS = (
    "score_version",
    "dimension_scores",
    "article_score",
    "final_score",
    "selection_status",
    "recommendation_reason",
    "scored_at",
    "scoring_method",
    "lane",
    "subjective_meta",
    "score_vocab_user_terms",
    "score_vocab_matched_user_terms",
)


def _clear_score_cache(meta: dict) -> None:
    for key in _SCORE_CACHE_KEYS:
        meta.pop(key, None)


def rescore_contents(*, dry_run: bool = False, limit: int | None = None) -> dict[str, int]:
    db = SessionLocal()
    stats: Counter[str] = Counter()
    try:
        query = db.query(Content).options(joinedload(Content.source)).order_by(Content.fetched_at.desc())
        if limit is not None:
            query = query.limit(limit)
        rows = query.all()

        keyword_rows: list = []
        matcher = KeywordMatcher()
        if KEYWORD_MONITORING_ENABLED:
            keyword_rows = db.query(Keyword).filter(Keyword.enabled == True).all()  # noqa: E712

        for content in rows:
            stats["total"] += 1
            apply_summary_cleaning(content)
            ensure_listing_summary(content)

            if KEYWORD_MONITORING_ENABLED and keyword_rows:
                content.keyword_matches = matcher.match(
                    content.title or "",
                    content.full_content or content.summary or "",
                    keyword_rows,
                )

            meta = dict(content.metadata_ or {})
            meta = merge_content_quality_metadata(
                meta,
                title=content.title or "",
                full_content=content.full_content,
                summary=content.summary,
                translated_summary=content.translated_summary,
            )

            source = content.source
            source_meta = source.metadata_ if source else {}
            accepted, accept_reason = assess_fetch_acceptance(content, meta)

            if not accepted:
                meta = stamp_fetch_acceptance_metadata(
                    meta,
                    accepted=False,
                    reason=accept_reason,
                    source_stars=(source_meta or {}).get("source_stars", 1),
                )
                _clear_score_cache(meta)
                content.metadata_ = meta
                stats["incomplete"] += 1
                continue

            meta = stamp_fetch_acceptance_metadata(meta, accepted=True, reason=accept_reason)
            _clear_score_cache(meta)
            meta = merge_baseline_scoring_metadata(
                meta,
                title=content.title or "",
                summary=content.summary,
                full_content=content.full_content,
                source_metadata=source_meta or {},
                content_type=content.content_type or "",
                content=content,
                keyword_objects=keyword_rows if KEYWORD_MONITORING_ENABLED else None,
                keyword_matches=content.keyword_matches if KEYWORD_MONITORING_ENABLED else None,
            )
            content.metadata_ = meta

            if meta.get("score_version") == SCORE_VERSION:
                stats["scored"] += 1
                status = str(meta.get("selection_status") or "")
                if status:
                    stats[f"status_{status}"] += 1
            else:
                stats["skipped"] += 1

        if dry_run:
            db.rollback()
        else:
            db.commit()
        return dict(stats)
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-score all contents with pim-score-v2")
    parser.add_argument("--dry-run", action="store_true", help="Compute scores without committing")
    parser.add_argument("--limit", type=int, default=None, help="Max rows to process")
    args = parser.parse_args()

    stats = rescore_contents(dry_run=args.dry_run, limit=args.limit)
    mode = "dry-run" if args.dry_run else "committed"
    print(f"rescore_contents ({mode}, {SCORE_VERSION}):")
    for key in sorted(stats):
        print(f"  {key}: {stats[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
