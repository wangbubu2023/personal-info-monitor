"""Background jobs to re-run cross-article relation inference."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.domains.atoms.relation_infer.worker import infer_relations
from app.domains.atoms.vocab import AtomType
from app.features import atoms_relations_enabled
from app.models.atom import Atom
from app.utils.datetime import utcnow_naive
from app.utils.logger import get_logger

logger = get_logger(__name__)

_jobs: dict[str, "ReconcileJob"] = {}
_lock = asyncio.Lock()

_ELIGIBLE = {AtomType.INFO.value, AtomType.DATA.value}


@dataclass
class ReconcileJob:
    job_id: str
    status: str = "pending"
    processed: int = 0
    total: int = 0
    relations_created: int = 0
    errors: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=utcnow_naive)
    finished_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "processed": self.processed,
            "total": self.total,
            "relations_created": self.relations_created,
            "errors": self.errors[:20],
            "created_at": self.created_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


def get_reconcile_job(job_id: str) -> ReconcileJob | None:
    return _jobs.get(job_id)


async def start_relations_reconcile(
    *,
    limit: int = 1000,
    since: str | None = None,
    atom_id: str | None = None,
    dry_run: bool = False,
) -> ReconcileJob:
    if not atoms_relations_enabled():
        raise RuntimeError("ATOMS_RELATIONS_ENABLED=false")

    job = ReconcileJob(job_id=str(uuid.uuid4()))
    async with _lock:
        _jobs[job.job_id] = job

    asyncio.create_task(
        _run_reconcile(job, limit=limit, since=since, atom_id=atom_id, dry_run=dry_run)
    )
    return job


def _query_atoms(session: Session, *, limit: int, since: str | None, atom_id: str | None) -> list[Atom]:
    query = session.query(Atom).filter(Atom.atom_type.in_(_ELIGIBLE))
    if atom_id:
        query = query.filter(Atom.atom_id == atom_id)
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00")).replace(tzinfo=None)
            query = query.filter(Atom.created_at >= since_dt)
        except ValueError:
            pass
    return query.order_by(Atom.created_at.desc()).limit(max(1, limit)).all()


async def _run_reconcile(
    job: ReconcileJob,
    *,
    limit: int,
    since: str | None,
    atom_id: str | None,
    dry_run: bool,
) -> None:
    job.status = "running"
    from app.database import SessionLocal

    session = SessionLocal()
    try:
        rows = _query_atoms(session, limit=limit, since=since, atom_id=atom_id)
        job.total = len(rows)

        for row in rows:
            if dry_run:
                job.processed += 1
                continue
            try:
                created = await infer_relations(row.atom_id)
                job.relations_created += created
            except Exception as exc:  # noqa: BLE001
                job.errors.append(f"{row.atom_id}: {exc}")
                logger.warning("reconcile infer failed for %s: %s", row.atom_id, exc)
            job.processed += 1

        job.status = "done"
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.errors.append(str(exc))
        logger.exception("relations reconcile job %s failed", job.job_id)
    finally:
        session.close()
        job.finished_at = utcnow_naive()


__all__ = ["ReconcileJob", "get_reconcile_job", "start_relations_reconcile"]
