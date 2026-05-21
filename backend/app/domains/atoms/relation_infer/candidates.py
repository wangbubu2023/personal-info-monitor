"""Rule-based candidate pairing for cross-article relation inference."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.domains.atoms.types import AtomRecord
from app.domains.atoms.vocab import AtomType, Domain
from app.models.atom import Atom

MAX_CANDIDATES = 50
TIME_WINDOW_DAYS = 30
_ELIGIBLE_TYPES = {AtomType.INFO.value, AtomType.DATA.value}


def extract_entity_names(atom_type: str, payload: dict) -> set[str]:
    names: set[str] = set()
    if atom_type == AtomType.INFO.value:
        for entity in payload.get("entities") or []:
            if entity:
                names.add(str(entity).strip())
        for who in payload.get("who") or []:
            if isinstance(who, dict) and who.get("name"):
                names.add(str(who["name"]).strip())
    elif atom_type == AtomType.DATA.value:
        for key in ("metric", "source_org"):
            value = payload.get(key)
            if value:
                names.add(str(value).strip())
    return {name for name in names if name}


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()[:10]
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _time_anchor(atom_type: str, payload: dict) -> tuple[datetime | None, str | None]:
    if atom_type == AtomType.INFO.value:
        return _parse_date(payload.get("when")), None
    if atom_type == AtomType.DATA.value:
        period = payload.get("period")
        period_text = str(period).strip() if period else None
        return _parse_date(period_text), period_text
    return None, None


def entities_overlap(left: set[str], right: set[str]) -> bool:
    if not left or not right:
        return False
    return bool(left & right)


def time_compatible(
    *,
    left_type: str,
    left_payload: dict,
    right_type: str,
    right_payload: dict,
) -> bool:
    left_dt, left_period = _time_anchor(left_type, left_payload)
    right_dt, right_period = _time_anchor(right_type, right_payload)

    if left_period and right_period and left_period == right_period:
        return True

    if left_dt and right_dt:
        return abs((left_dt - right_dt).days) <= TIME_WINDOW_DAYS

    if left_dt is None and right_dt is None:
        return True

    return False


def _atom_row_to_record(row: Atom) -> AtomRecord:
    return AtomRecord(
        atom_id=row.atom_id,
        content_id=str(row.content_id),
        atom_type=AtomType(row.atom_type),
        domain=Domain(row.domain),
        source_sentence=row.source_sentence,
        source_url=row.source_url,
        atom_source=row.atom_source,
        payload=dict(row.payload or {}),
        verified=bool(row.verified),
        source_credibility=float(row.source_credibility),
        fact_confidence=float(row.fact_confidence),
        schema_version=int(row.schema_version),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def find_candidates(session: Session, atom: AtomRecord) -> list[AtomRecord]:
    """Return cross-content atoms that may relate to *atom* (rule filter only)."""
    if atom.atom_type.value not in _ELIGIBLE_TYPES:
        return []

    source_entities = extract_entity_names(atom.atom_type.value, atom.payload)
    if not source_entities:
        return []

    rows = (
        session.query(Atom)
        .filter(
            Atom.domain == atom.domain.value,
            Atom.content_id != atom.content_id,
            Atom.atom_type.in_(_ELIGIBLE_TYPES),
        )
        .order_by(Atom.created_at.desc())
        .limit(500)
        .all()
    )

    candidates: list[AtomRecord] = []
    for row in rows:
        if len(candidates) >= MAX_CANDIDATES:
            break
        other = _atom_row_to_record(row)
        other_entities = extract_entity_names(other.atom_type.value, other.payload)
        if not entities_overlap(source_entities, other_entities):
            continue
        if not time_compatible(
            left_type=atom.atom_type.value,
            left_payload=atom.payload,
            right_type=other.atom_type.value,
            right_payload=other.payload,
        ):
            continue
        candidates.append(other)

    return candidates


__all__ = [
    "MAX_CANDIDATES",
    "TIME_WINDOW_DAYS",
    "entities_overlap",
    "extract_entity_names",
    "find_candidates",
    "time_compatible",
]
