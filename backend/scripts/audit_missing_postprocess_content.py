#!/usr/bin/env python3
"""Audit legacy postprocess successes whose Content row no longer exists.

The command is dry-run by default. Pass ``--apply`` to mark impossible legacy
successes dead with the stable ``CONTENT_NOT_FOUND`` failure code.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.fspath(backend_dir))

from app.database import SessionLocal
from app.models import Content, PostprocessJob
from app.utils.datetime import utcnow_naive


def audit_missing_content(*, apply: bool = False) -> dict:
    db = SessionLocal()
    try:
        rows = (
            db.query(PostprocessJob)
            .outerjoin(Content, Content.id == PostprocessJob.content_id)
            .filter(PostprocessJob.status == "succeeded", Content.id.is_(None))
            .order_by(PostprocessJob.created_at.asc())
            .all()
        )
        findings = [
            {
                "job_id": str(row.id),
                "content_id": str(row.content_id),
                "idempotency_key": row.idempotency_key,
                "previous_status": row.status,
                "failure_code": "CONTENT_NOT_FOUND",
            }
            for row in rows
        ]
        if apply and rows:
            now = utcnow_naive()
            for row in rows:
                row.status = "dead"
                row.failure_code = "CONTENT_NOT_FOUND"
                row.failure_severity = "error"
                row.failure_retryable = False
                row.last_error = "[CONTENT_NOT_FOUND] Content row does not exist"
                row.finished_at = now
                row.updated_at = now
            db.commit()
        return {"mode": "apply" if apply else "dry-run", "count": len(findings), "findings": findings}
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="mark findings dead; default is dry-run")
    args = parser.parse_args()
    print(json.dumps(audit_missing_content(apply=args.apply), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
