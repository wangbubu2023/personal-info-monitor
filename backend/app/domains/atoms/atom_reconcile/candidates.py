"""Candidate retrieval for reconcile: rule route (A) + FTS-like route (B).

Embedding route (C) is intentionally deferred — short term A+B is sufficient and
avoids standing up a vector store.
"""

from __future__ import annotations

from sqlalchemy import String, or_
from sqlalchemy.orm import Session

from app.domains.atoms.relation_infer.candidates import (
    _atom_row_to_record,
    extract_entity_names,
    find_candidates,
)
from app.domains.atoms.types import AtomRecord
from app.domains.atoms.vocab import AtomStatus
from app.models.atom import Atom

MAX_RECONCILE_CANDIDATES = 30
_KEYWORD_MIN_LEN = 2


def _keywords(atom: AtomRecord) -> list[str]:
    names = extract_entity_names(atom.atom_type.value, atom.payload)
    return [n for n in names if len(n) >= _KEYWORD_MIN_LEN]


def _fts_candidates(session: Session, atom: AtomRecord, *, exclude: set[str]) -> list[AtomRecord]:
    keywords = _keywords(atom)
    if not keywords:
        return []
    clauses = []
    for kw in keywords[:5]:
        term = f"%{kw}%"
        clauses.append(Atom.canonical_text.like(term))
        clauses.append(Atom.source_sentence.like(term))
        clauses.append(Atom.payload.cast(String).like(term))
    rows = (
        session.query(Atom)
        .filter(
            Atom.content_id != atom.content_id,
            Atom.status == AtomStatus.ACTIVE.value,
            or_(*clauses),
        )
        .order_by(Atom.created_at.desc())
        .limit(MAX_RECONCILE_CANDIDATES * 2)
        .all()
    )
    out: list[AtomRecord] = []
    for row in rows:
        if row.atom_id in exclude:
            continue
        out.append(_atom_row_to_record(row))
    return out


def find_reconcile_candidates(session: Session, atom: AtomRecord) -> list[AtomRecord]:
    """Return existing active atoms that may relate to *atom* (rule + FTS union)."""
    seen: set[str] = {atom.atom_id}
    results: list[AtomRecord] = []

    for candidate in find_candidates(session, atom):
        if candidate.atom_id in seen:
            continue
        seen.add(candidate.atom_id)
        results.append(candidate)

    for candidate in _fts_candidates(session, atom, exclude=seen):
        if candidate.atom_id in seen:
            continue
        seen.add(candidate.atom_id)
        results.append(candidate)
        if len(results) >= MAX_RECONCILE_CANDIDATES:
            break

    return results[:MAX_RECONCILE_CANDIDATES]


__all__ = ["MAX_RECONCILE_CANDIDATES", "find_reconcile_candidates"]
