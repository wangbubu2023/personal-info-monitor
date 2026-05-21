"""SQLAlchemy repository for cross-article atom relations (P2)."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.domains.atoms.id_gen import next_rel_id
from app.domains.atoms.types import RelationCreate, RelationRecord, RelationUpdate
from app.domains.atoms.vocab import RelationDirection, RelationType
from app.models.atom import Atom, AtomRelation
from app.utils.datetime import utcnow_naive

CONFIDENCE_BOOST = 0.05


@dataclass(frozen=True)
class RelationListFilters:
    atom_id: str | None = None
    verified: bool | None = None


def _row_to_record(row: AtomRelation) -> RelationRecord:
    return RelationRecord(
        rel_id=row.rel_id,
        atom_a=row.atom_a,
        atom_b=row.atom_b,
        relation_type=RelationType(row.relation_type),
        direction=RelationDirection(row.direction),
        verified=bool(row.verified),
        fact_confidence=float(row.fact_confidence),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlAtomRelationRepository:
    def __init__(self, session_factory):
        self._session_factory = session_factory

    def upsert_relation(self, data: RelationCreate) -> RelationRecord:
        session: Session = self._session_factory()
        try:
            existing = (
                session.query(AtomRelation)
                .filter(
                    AtomRelation.atom_a == data.atom_a,
                    AtomRelation.atom_b == data.atom_b,
                )
                .first()
            )
            if existing is not None and existing.verified:
                return _row_to_record(existing)

            if existing is None:
                row = AtomRelation(
                    rel_id=next_rel_id(session),
                    atom_a=data.atom_a,
                    atom_b=data.atom_b,
                    relation_type=data.relation_type.value,
                    direction=data.direction.value,
                    verified=data.verified,
                    fact_confidence=data.fact_confidence,
                )
                session.add(row)
            else:
                existing.relation_type = data.relation_type.value
                existing.direction = data.direction.value
                existing.fact_confidence = data.fact_confidence
                if not existing.verified:
                    existing.verified = data.verified
                existing.updated_at = utcnow_naive()
                row = existing

            session.commit()
            session.refresh(row)
            return _row_to_record(row)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_relation(self, rel_id: str) -> RelationRecord | None:
        session: Session = self._session_factory()
        try:
            row = session.get(AtomRelation, rel_id)
            return _row_to_record(row) if row else None
        finally:
            session.close()

    def update_relation(self, rel_id: str, patch: RelationUpdate) -> RelationRecord | None:
        session: Session = self._session_factory()
        try:
            row = session.get(AtomRelation, rel_id)
            if row is None:
                return None
            was_verified = bool(row.verified)
            if patch.relation_type is not None:
                row.relation_type = patch.relation_type.value
            if patch.direction is not None:
                row.direction = patch.direction.value
            if patch.fact_confidence is not None:
                row.fact_confidence = patch.fact_confidence
            if patch.verified is not None:
                row.verified = patch.verified
            row.updated_at = utcnow_naive()
            session.commit()
            session.refresh(row)
            record = _row_to_record(row)
            if (
                not was_verified
                and record.verified
                and record.relation_type == RelationType.CORROBORATION
            ):
                self._apply_corroboration_boost(session, row.atom_a, row.atom_b)
                session.commit()
            return record
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def list_relations(
        self,
        filters: RelationListFilters,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[RelationRecord], int]:
        session: Session = self._session_factory()
        try:
            query = session.query(AtomRelation)
            if filters.atom_id:
                query = query.filter(
                    or_(
                        AtomRelation.atom_a == filters.atom_id,
                        AtomRelation.atom_b == filters.atom_id,
                    )
                )
            if filters.verified is not None:
                query = query.filter(AtomRelation.verified.is_(filters.verified))
            total = query.count()
            rows = (
                query.order_by(AtomRelation.created_at.desc())
                .offset(max(page - 1, 0) * page_size)
                .limit(page_size)
                .all()
            )
            return [_row_to_record(row) for row in rows], total
        finally:
            session.close()

    def list_relations_for_atom(self, atom_id: str) -> list[RelationRecord]:
        session: Session = self._session_factory()
        try:
            rows = (
                session.query(AtomRelation)
                .filter(
                    or_(
                        AtomRelation.atom_a == atom_id,
                        AtomRelation.atom_b == atom_id,
                    )
                )
                .order_by(AtomRelation.created_at.desc())
                .all()
            )
            return [_row_to_record(row) for row in rows]
        finally:
            session.close()

    def delete_relation(self, rel_id: str) -> bool:
        session: Session = self._session_factory()
        try:
            row = session.get(AtomRelation, rel_id)
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def apply_verified_corroboration(self, rel_id: str) -> RelationRecord | None:
        """Raise both endpoint atoms' fact_confidence when a corroboration is verified."""
        session: Session = self._session_factory()
        try:
            row = session.get(AtomRelation, rel_id)
            if row is None:
                return None
            if RelationType(row.relation_type) != RelationType.CORROBORATION:
                return _row_to_record(row)
            if not row.verified:
                row.verified = True
                row.updated_at = utcnow_naive()
            self._apply_corroboration_boost(session, row.atom_a, row.atom_b)
            session.commit()
            session.refresh(row)
            return _row_to_record(row)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @staticmethod
    def _apply_corroboration_boost(session: Session, atom_a: str, atom_b: str) -> None:
        for atom_id in (atom_a, atom_b):
            atom = session.get(Atom, atom_id)
            if atom is None:
                continue
            atom.fact_confidence = min(1.0, float(atom.fact_confidence) + CONFIDENCE_BOOST)
            atom.updated_at = utcnow_naive()


def default_atom_relations_repository() -> SqlAtomRelationRepository:
    from app.database import SessionLocal

    return SqlAtomRelationRepository(SessionLocal)


__all__ = [
    "CONFIDENCE_BOOST",
    "RelationListFilters",
    "SqlAtomRelationRepository",
    "default_atom_relations_repository",
]
