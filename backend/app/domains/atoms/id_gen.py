"""Generate ATOM-/REL- identifiers with daily sequences."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.atom import AtomIdSequence
from app.utils.datetime import utcnow_naive


def _today_prefix(kind: str) -> str:
    day = utcnow_naive().strftime("%Y%m%d")
    return f"{kind}-{day}"


def _next_id(session: Session, kind: str) -> str:
    prefix = _today_prefix(kind)
    row = session.get(AtomIdSequence, prefix)
    if row is None:
        row = AtomIdSequence(prefix=prefix, last_seq=0)
        session.add(row)
        session.flush()
    row.last_seq += 1
    session.flush()
    return f"{prefix}-{row.last_seq:05d}"


def next_atom_id(session: Session) -> str:
    return _next_id(session, "ATOM")


def next_rel_id(session: Session) -> str:
    return _next_id(session, "REL")


def next_operation_id(session: Session) -> str:
    return _next_id(session, "OP")


__all__ = ["next_atom_id", "next_operation_id", "next_rel_id"]
