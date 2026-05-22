#!/usr/bin/env python3
"""Summarize ScoreFeedback to guide score calibration.

Usage:
    cd backend
    .venv/bin/python scripts/feedback_summary.py
    .venv/bin/python scripts/feedback_summary.py --min-count 3
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("DATABASE_URL", "sqlite:///pim.db")

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.score_feedback import ScoreFeedback
from app.models.content import Content


def _get_engine():
    settings = get_settings()
    db_url = str(getattr(settings, "database_url", None) or "sqlite:///pim.db")
    # Strip async driver for sync session
    return create_engine(db_url.replace("+aiosqlite", "").replace("sqlite+aiosqlite", "sqlite"))


def summarize(*, min_count: int = 1) -> None:
    engine = _get_engine()
    try:
        with Session(engine) as session:
            rows = session.execute(
                select(ScoreFeedback, Content.title)
                .join(Content, Content.id == ScoreFeedback.content_id)
                .order_by(ScoreFeedback.created_at.desc())
            ).all()
    except Exception as exc:
        if "no such table" in str(exc).lower():
            print("score_feedback table not found — run: alembic upgrade head")
        else:
            print(f"Error querying feedback: {exc}")
        return

    if not rows:
        print("No feedback recorded yet.")
        return

    total = len(rows)
    direction_counter: Counter = Counter()
    lane_direction: dict[str, Counter] = defaultdict(Counter)
    expected_status_counter: Counter = Counter()
    score_deltas: list[float] = []
    notes: list[str] = []

    for feedback, title in rows:
        direction_counter[feedback.direction] += 1
        snap = feedback.snapshot or {}
        lane = snap.get("lane") or "unknown"
        lane_direction[lane][feedback.direction] += 1
        if feedback.expected_status:
            expected_status_counter[feedback.expected_status] += 1
        delta = snap.get("score_delta")
        if delta is not None:
            try:
                score_deltas.append(float(delta))
            except (TypeError, ValueError):
                pass
        if feedback.note:
            notes.append(f"  [{feedback.direction}] {(title or '')[:60]}: {feedback.note}")

    print(f"\n{'='*60}")
    print(f"Score Feedback Summary  (total: {total})")
    print(f"{'='*60}")

    print("\n--- Overall Direction ---")
    for direction in ("too_high", "too_low", "ok"):
        count = direction_counter.get(direction, 0)
        pct = count / total * 100
        print(f"  {direction:12s}: {count:4d}  ({pct:.1f}%)")

    print("\n--- By Lane x Direction ---")
    for lane, counts in sorted(lane_direction.items()):
        lane_total = sum(counts.values())
        if lane_total < min_count:
            continue
        parts = [f"{d}={counts[d]}" for d in ("too_high", "too_low", "ok") if counts[d]]
        print(f"  {lane:20s}: {'  '.join(parts)}")

    if expected_status_counter:
        print("\n--- Expected Status (user disagreement) ---")
        for status, count in expected_status_counter.most_common():
            print(f"  {status}: {count}")

    if score_deltas:
        avg_delta = sum(score_deltas) / len(score_deltas)
        print(f"\n--- Score Delta (recomputed - stored) ---")
        print(f"  mean delta: {avg_delta:+.2f}  (positive = vocab change inflated score)")

    if notes:
        print(f"\n--- Notes ({len(notes)}) ---")
        for note in notes[:20]:
            print(note)
        if len(notes) > 20:
            print(f"  ... and {len(notes) - 20} more")

    print("\n--- Calibration Hints ---")
    high_pct = direction_counter.get("too_high", 0) / total
    low_pct = direction_counter.get("too_low", 0) / total
    if high_pct > 0.4:
        print("  WARNING: >40% too_high — consider raising selected_threshold or tightening vocab caps")
    if low_pct > 0.4:
        print("  WARNING: >40% too_low  — consider lowering thresholds or expanding entity tiers")
    if high_pct <= 0.4 and low_pct <= 0.4:
        print("  OK: Distribution looks balanced")


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize ScoreFeedback for score calibration")
    parser.add_argument("--min-count", type=int, default=1,
                        help="Min feedback count per lane to display (default: 1)")
    args = parser.parse_args()
    summarize(min_count=args.min_count)


if __name__ == "__main__":
    main()
