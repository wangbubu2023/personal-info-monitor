"""SQLAlchemy repository for event clusters and summaries."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.domains.atoms.id_gen import next_event_id, next_summary_id
from app.models.atom_event import EventCluster, EventClusterAtom, EventSummary
from app.utils.datetime import utcnow_naive
from app.utils.logger import get_logger

logger = get_logger(__name__)


class SqlEventRepository:
    def __init__(self, session_factory):
        self._session_factory = session_factory

    def create_cluster(self, *, title: str, domain: str, seen_at: datetime | None = None) -> str:
        session: Session = self._session_factory()
        try:
            event_id = next_event_id(session)
            now = seen_at or utcnow_naive()
            session.add(
                EventCluster(
                    event_id=event_id,
                    title=title[:500],
                    domain=domain,
                    status="active",
                    first_seen_at=now,
                    last_seen_at=now,
                )
            )
            session.commit()
            return event_id
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def attach_atom(self, event_id: str, atom_id: str, *, role: str = "background", seen_at: datetime | None = None) -> bool:
        session: Session = self._session_factory()
        try:
            exists = (
                session.query(EventClusterAtom)
                .filter(EventClusterAtom.event_id == event_id, EventClusterAtom.atom_id == atom_id)
                .first()
            )
            if exists is None:
                session.add(EventClusterAtom(event_id=event_id, atom_id=atom_id, role=role))
            cluster = session.get(EventCluster, event_id)
            if cluster is not None and seen_at is not None:
                if cluster.last_seen_at is None or seen_at > cluster.last_seen_at:
                    cluster.last_seen_at = seen_at
                cluster.updated_at = utcnow_naive()
            session.commit()
            return exists is None
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def list_atom_ids(self, event_id: str) -> list[str]:
        session: Session = self._session_factory()
        try:
            rows = (
                session.query(EventClusterAtom.atom_id)
                .filter(EventClusterAtom.event_id == event_id)
                .all()
            )
            return [r[0] for r in rows]
        finally:
            session.close()

    def list_clusters(self, *, domain: str | None = None, limit: int = 50) -> list[dict]:
        session: Session = self._session_factory()
        try:
            query = session.query(EventCluster)
            if domain:
                query = query.filter(EventCluster.domain == domain)
            rows = query.order_by(EventCluster.last_seen_at.desc()).limit(max(1, limit)).all()
            out: list[dict] = []
            for row in rows:
                count = (
                    session.query(EventClusterAtom)
                    .filter(EventClusterAtom.event_id == row.event_id)
                    .count()
                )
                out.append(
                    {
                        "event_id": row.event_id,
                        "title": row.title,
                        "domain": row.domain,
                        "status": row.status,
                        "atom_count": int(count),
                        "canonical_summary": row.canonical_summary,
                        "first_seen_at": row.first_seen_at.isoformat() if row.first_seen_at else None,
                        "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
                    }
                )
            return out
        finally:
            session.close()

    def add_summary(
        self,
        event_id: str,
        *,
        summary: str,
        source_atom_ids: list[str],
        model: str | None = None,
        window_start: datetime | None = None,
        window_end: datetime | None = None,
    ) -> str:
        session: Session = self._session_factory()
        try:
            summary_id = next_summary_id(session)
            session.add(
                EventSummary(
                    summary_id=summary_id,
                    event_id=event_id,
                    summary=summary,
                    model=model,
                    source_atom_ids=list(source_atom_ids),
                    window_start=window_start,
                    window_end=window_end,
                )
            )
            cluster = session.get(EventCluster, event_id)
            if cluster is not None:
                cluster.canonical_summary = summary
                cluster.updated_at = utcnow_naive()
            session.commit()
            return summary_id
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


def default_event_repository() -> SqlEventRepository:
    from app.database import SessionLocal

    return SqlEventRepository(SessionLocal)


__all__ = ["SqlEventRepository", "default_event_repository"]
