"""Background backfill jobs for atom extraction."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import joinedload

from app.database import SessionLocal
from app.domains.atoms.atomizer import atomize_content_async
from app.features import atoms_enabled
from app.models import Content
from app.utils.datetime import utcnow_naive
from app.utils.logger import get_logger

logger = get_logger(__name__)

_jobs: dict[str, "BackfillJob"] = {}
_lock = asyncio.Lock()


@dataclass
class BackfillJob:
    job_id: str
    status: str = "pending"
    processed: int = 0
    total: int = 0
    errors: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=utcnow_naive)
    finished_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "processed": self.processed,
            "total": self.total,
            "errors": self.errors[:20],
            "created_at": self.created_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


def get_backfill_job(job_id: str) -> BackfillJob | None:
    return _jobs.get(job_id)


async def start_backfill(
    *,
    limit: int = 500,
    since: str | None = None,
    content_id: str | None = None,
    dry_run: bool = False,
) -> BackfillJob:
    if not atoms_enabled():
        raise RuntimeError("ATOMS_ENABLED=false")

    job = BackfillJob(job_id=str(uuid.uuid4()))
    async with _lock:
        _jobs[job.job_id] = job

    asyncio.create_task(_run_backfill(job, limit=limit, since=since, content_id=content_id, dry_run=dry_run))
    return job


async def _run_backfill(
    job: BackfillJob,
    *,
    limit: int,
    since: str | None,
    content_id: str | None,
    dry_run: bool,
) -> None:
    job.status = "running"
    session = SessionLocal()
    try:
        query = session.query(Content).options(joinedload(Content.source))
        if content_id:
            query = query.filter(Content.id == content_id)
        if since:
            try:
                since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
                query = query.filter(Content.created_at >= since_dt.replace(tzinfo=None))
            except ValueError:
                job.errors.append(f"invalid since date: {since}")
        rows = query.order_by(Content.created_at.desc()).limit(max(1, limit)).all()
        job.total = len(rows)

        for row in rows:
            if dry_run:
                job.processed += 1
                continue
            try:
                await atomize_content_async(str(row.id))
            except Exception as exc:  # noqa: BLE001
                job.errors.append(f"{row.id}: {exc}")
                logger.warning("backfill atomize failed for %s: %s", row.id, exc)
            job.processed += 1

        job.status = "done"
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.errors.append(str(exc))
        logger.exception("backfill job %s failed", job.job_id)
    finally:
        session.close()
        job.finished_at = utcnow_naive()


__all__ = ["BackfillJob", "get_backfill_job", "start_backfill"]
