"""Minimal, queryable business lineage edges."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.reliable_execution import LineageEdge
from app.platform.persistence.database import SessionLocal


@dataclass(frozen=True)
class LineageRef:
    object_type: str
    object_id: str


def add_lineage_edge(
    *,
    from_type: str,
    from_id: str,
    to_type: str,
    to_id: str,
    relation: str,
    pipeline_version: str | None = None,
    trace_id: str | None = None,
    metadata: dict | None = None,
    session: Session | None = None,
) -> bool:
    """Add an idempotent edge, optionally inside the caller's transaction."""
    owns_session = session is None
    db = session or SessionLocal()
    try:
        existing = db.query(LineageEdge.id).filter(
            LineageEdge.from_type == str(from_type),
            LineageEdge.from_id == str(from_id),
            LineageEdge.to_type == str(to_type),
            LineageEdge.to_id == str(to_id),
            LineageEdge.relation == str(relation),
        ).first()
        if existing is not None:
            return False
        db.add(
            LineageEdge(
                from_type=str(from_type),
                from_id=str(from_id),
                to_type=str(to_type),
                to_id=str(to_id),
                relation=str(relation),
                pipeline_version=pipeline_version,
                trace_id=trace_id,
                metadata_=metadata or {},
            )
        )
        if owns_session:
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                return False
        else:
            db.flush()
        return True
    finally:
        if owns_session:
            db.close()


def trace_lineage(
    object_type: str,
    object_id: str,
    *,
    direction: str = "upstream",
    max_hops: int = 3,
) -> list[dict[str, object]]:
    """Breadth-first traversal bounded by hop count."""
    db = SessionLocal()
    try:
        frontier = deque([(LineageRef(str(object_type), str(object_id)), 0)])
        seen = {(str(object_type), str(object_id))}
        result: list[dict[str, object]] = []
        while frontier:
            current, hop = frontier.popleft()
            if hop >= max(0, int(max_hops)):
                continue
            if direction == "downstream":
                rows = db.query(LineageEdge).filter(
                    LineageEdge.from_type == current.object_type,
                    LineageEdge.from_id == current.object_id,
                ).all()
                next_ref = lambda edge: LineageRef(edge.to_type, edge.to_id)
            else:
                rows = db.query(LineageEdge).filter(
                    LineageEdge.to_type == current.object_type,
                    LineageEdge.to_id == current.object_id,
                ).all()
                next_ref = lambda edge: LineageRef(edge.from_type, edge.from_id)
            for edge in rows:
                result.append(
                    {
                        "hop": hop + 1,
                        "from_type": edge.from_type,
                        "from_id": edge.from_id,
                        "to_type": edge.to_type,
                        "to_id": edge.to_id,
                        "relation": edge.relation,
                        "pipeline_version": edge.pipeline_version,
                        "trace_id": edge.trace_id,
                    }
                )
                ref = next_ref(edge)
                key = (ref.object_type, ref.object_id)
                if key not in seen:
                    seen.add(key)
                    frontier.append((ref, hop + 1))
        return result
    finally:
        db.close()


__all__ = ["add_lineage_edge", "trace_lineage"]
