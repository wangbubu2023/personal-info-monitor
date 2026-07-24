#!/usr/bin/env python3
"""Checkpointed Event v1 signature/membership backfill."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.database import SessionLocal
from app.domains.events.engine import backfill_event_v1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cursor")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--checkpoint", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    cursor = args.cursor
    if cursor is None and args.checkpoint and args.checkpoint.is_file():
        payload = json.loads(args.checkpoint.read_text(encoding="utf-8"))
        cursor = str(payload.get("last_cursor") or "") or None
    db = SessionLocal()
    try:
        result = backfill_event_v1(
            db,
            cursor=cursor,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
        )
        if args.dry_run:
            db.rollback()
        else:
            db.commit()
        if args.checkpoint:
            args.checkpoint.parent.mkdir(parents=True, exist_ok=True)
            args.checkpoint.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
