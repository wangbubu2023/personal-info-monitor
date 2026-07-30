#!/usr/bin/env python3
"""Reclassify stored content lanes without changing scores or selection status.

Dry-run is the default. Pass ``--apply`` only after reviewing the transition
summary. Both the indexed ``contents.lane`` column and metadata ``lane`` value
are updated together.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from typing import Any

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)

from dotenv import load_dotenv

load_dotenv(os.path.join(backend_dir, ".env"))

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.domains.score.score_rules import classify_lane
from app.domains.score.scoring import SCORE_VERSION
from app.models import Content


def reclassify_content_lanes(db: Session, *, limit: int | None = None) -> dict[str, Any]:
    query = db.query(Content).order_by(Content.fetched_at.desc(), Content.id.desc())
    if limit is not None:
        query = query.limit(limit)

    transitions: Counter[str] = Counter()
    changed = unchanged = 0
    lane_reclassified = storage_repaired = version_stamped = 0
    for content in query.all():
        metadata = dict(content.metadata_ or {})
        old_lane = str(content.lane or metadata.get("lane") or "").strip() or "<NULL>"
        new_lane = classify_lane(
            content.title or "",
            content.summary,
            content.full_content,
        )
        transitions[f"{old_lane}->{new_lane}"] += 1
        column_is_current = content.lane == new_lane
        metadata_is_current = metadata.get("lane") == new_lane
        version_is_current = metadata.get("lane_classification_version") == SCORE_VERSION
        if column_is_current and metadata_is_current and version_is_current:
            unchanged += 1
            continue

        if old_lane != new_lane:
            lane_reclassified += 1
        elif not column_is_current or not metadata_is_current:
            storage_repaired += 1
        else:
            version_stamped += 1
        metadata["lane"] = new_lane
        metadata["lane_classification_version"] = SCORE_VERSION
        content.metadata_ = metadata
        content.lane = new_lane
        changed += 1

    return {
        "score_version": SCORE_VERSION,
        "total": changed + unchanged,
        "changed": changed,
        "unchanged": unchanged,
        "lane_reclassified": lane_reclassified,
        "storage_repaired": storage_repaired,
        "version_stamped": version_stamped,
        "transitions": dict(sorted(transitions.items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Reclassify content lanes only")
    parser.add_argument("--apply", action="store_true", help="Commit lane changes; default is dry-run")
    parser.add_argument("--limit", type=int, default=None, help="Maximum rows to inspect")
    args = parser.parse_args()

    with SessionLocal() as db:
        report = reclassify_content_lanes(db, limit=args.limit)
        if args.apply:
            db.commit()
        else:
            db.rollback()
    report["mode"] = "applied" if args.apply else "dry-run"
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
