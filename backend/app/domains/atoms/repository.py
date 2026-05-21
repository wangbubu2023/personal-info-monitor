"""SQLAlchemy repository for normalized atoms."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import String, func, or_
from sqlalchemy.orm import Session

from app.domains.atoms.id_gen import next_atom_id
from app.domains.atoms.schema import CURRENT_SCHEMA_VERSION
from app.domains.atoms.types import AtomCreate, AtomRecord, AtomUpdate
from app.domains.atoms.vocab import AtomType
from app.features import atoms_enabled
from app.models.atom import Atom
from app.utils.datetime import utcnow_naive
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class AtomListFilters:
    atom_type: str | None = None
    domain: str | None = None
    verified: bool | None = None
    atom_source: str | None = None
    content_id: str | None = None
    search: str | None = None


def _row_to_record(row: Atom) -> AtomRecord:
    return AtomRecord(
        atom_id=row.atom_id,
        content_id=str(row.content_id),
        atom_type=AtomType(row.atom_type),
        domain=row.domain,
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


class SqlAtomRepository:
    def __init__(self, session_factory):
        self._session_factory = session_factory

    def create_atom(self, data: AtomCreate) -> AtomRecord:
        session: Session = self._session_factory()
        try:
            existing = (
                session.query(Atom)
                .filter(
                    Atom.content_id == data.content_id,
                    Atom.source_sentence == data.source_sentence,
                    Atom.atom_type == data.atom_type.value,
                )
                .first()
            )
            if existing is not None:
                self._update_row(session, existing, data)
                session.commit()
                session.refresh(existing)
                return _row_to_record(existing)

            row = Atom(
                atom_id=next_atom_id(session),
                content_id=data.content_id,
                atom_type=data.atom_type.value,
                domain=data.domain.value,
                source_sentence=data.source_sentence,
                source_url=data.source_url,
                atom_source=data.atom_source,
                payload=data.payload.model_dump(mode="json"),
                verified=data.verified,
                source_credibility=data.source_credibility,
                fact_confidence=data.fact_confidence,
                schema_version=CURRENT_SCHEMA_VERSION,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return _row_to_record(row)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_atom(self, atom_id: str) -> AtomRecord | None:
        session: Session = self._session_factory()
        try:
            row = session.get(Atom, atom_id)
            return _row_to_record(row) if row else None
        finally:
            session.close()

    def update_atom(self, atom_id: str, patch: AtomUpdate) -> AtomRecord | None:
        session: Session = self._session_factory()
        try:
            row = session.get(Atom, atom_id)
            if row is None:
                return None
            if patch.domain is not None:
                row.domain = patch.domain.value
            if patch.atom_source is not None:
                row.atom_source = patch.atom_source
            if patch.source_credibility is not None:
                row.source_credibility = patch.source_credibility
            if patch.fact_confidence is not None:
                row.fact_confidence = patch.fact_confidence
            if patch.verified is not None:
                row.verified = patch.verified
            if patch.payload is not None:
                row.payload = patch.payload.model_dump(mode="json")
            row.updated_at = utcnow_naive()
            session.commit()
            session.refresh(row)
            return _row_to_record(row)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def list_atoms(
        self,
        filters: AtomListFilters,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[AtomRecord], int]:
        session: Session = self._session_factory()
        try:
            query = session.query(Atom)
            if filters.atom_type:
                query = query.filter(Atom.atom_type == filters.atom_type)
            if filters.domain:
                query = query.filter(Atom.domain == filters.domain)
            if filters.verified is not None:
                query = query.filter(Atom.verified.is_(filters.verified))
            if filters.atom_source:
                query = query.filter(Atom.atom_source.contains(filters.atom_source))
            if filters.content_id:
                query = query.filter(Atom.content_id == filters.content_id)
            if filters.search:
                term = f"%{filters.search.strip()}%"
                query = query.filter(
                    or_(
                        Atom.source_sentence.like(term),
                        Atom.atom_source.like(term),
                        Atom.payload.cast(String).like(term),
                    )
                )
            total = query.count()
            rows = (
                query.order_by(Atom.created_at.desc())
                .offset(max(page - 1, 0) * page_size)
                .limit(page_size)
                .all()
            )
            return [_row_to_record(row) for row in rows], total
        finally:
            session.close()

    def stats(self) -> dict[str, Any]:
        session: Session = self._session_factory()
        try:
            total = session.query(func.count(Atom.atom_id)).scalar() or 0
            verified_count = (
                session.query(func.count(Atom.atom_id)).filter(Atom.verified.is_(True)).scalar() or 0
            )
            by_type = dict(
                session.query(Atom.atom_type, func.count(Atom.atom_id))
                .group_by(Atom.atom_type)
                .all()
            )
            by_domain = dict(
                session.query(Atom.domain, func.count(Atom.atom_id))
                .group_by(Atom.domain)
                .all()
            )
            return {
                "total": int(total),
                "by_type": {str(k): int(v) for k, v in by_type.items()},
                "by_domain": {str(k): int(v) for k, v in by_domain.items()},
                "verified_count": int(verified_count),
                "unverified_count": int(total) - int(verified_count),
            }
        finally:
            session.close()

    def upsert_atoms_for_content(self, content_id: str, atoms: list[AtomCreate]) -> list[AtomRecord]:
        session: Session = self._session_factory()
        try:
            existing_rows = (
                session.query(Atom).filter(Atom.content_id == content_id).all()
            )
            existing_map = {
                (row.source_sentence, row.atom_type): row for row in existing_rows
            }
            seen_keys: set[tuple[str, str]] = set()
            results: list[AtomRecord] = []

            for item in atoms:
                key = (item.source_sentence, item.atom_type.value)
                seen_keys.add(key)
                row = existing_map.get(key)
                if row is None:
                    row = Atom(
                        atom_id=next_atom_id(session),
                        content_id=content_id,
                        atom_type=item.atom_type.value,
                        domain=item.domain.value,
                        source_sentence=item.source_sentence,
                        source_url=item.source_url,
                        atom_source=item.atom_source,
                        payload=item.payload.model_dump(mode="json"),
                        verified=item.verified,
                        source_credibility=item.source_credibility,
                        fact_confidence=item.fact_confidence,
                        schema_version=CURRENT_SCHEMA_VERSION,
                    )
                    session.add(row)
                else:
                    row = self._update_row(session, row, item, preserve_verified=True)
                session.flush()
                results.append(_row_to_record(row))

            for row in existing_rows:
                key = (row.source_sentence, row.atom_type)
                if key not in seen_keys and not row.verified:
                    session.delete(row)

            session.commit()
            return results
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def list_atoms_for_content(self, content_id: str) -> list[AtomRecord]:
        session: Session = self._session_factory()
        try:
            rows = (
                session.query(Atom)
                .filter(Atom.content_id == content_id)
                .order_by(Atom.created_at.asc())
                .all()
            )
            return [_row_to_record(row) for row in rows]
        finally:
            session.close()

    @staticmethod
    def _update_row(
        session: Session,
        row: Atom,
        data: AtomCreate,
        *,
        preserve_verified: bool = False,
    ) -> Atom:
        row.domain = data.domain.value
        row.source_url = data.source_url
        row.atom_source = data.atom_source
        row.payload = data.payload.model_dump(mode="json")
        row.source_credibility = data.source_credibility
        row.fact_confidence = data.fact_confidence
        if not preserve_verified or not row.verified:
            row.verified = data.verified
        row.schema_version = CURRENT_SCHEMA_VERSION
        row.updated_at = utcnow_naive()
        session.flush()
        return row


class SqlAtomReader:
    """Concrete :class:`AtomReader` backed by SQLAlchemy."""

    def __init__(self, session_factory):
        self._repo = SqlAtomRepository(session_factory)

    def get_atoms_for_content(self, content_id: str) -> tuple[AtomRecord, ...]:
        if not atoms_enabled():
            return ()
        try:
            return tuple(self._repo.list_atoms_for_content(content_id))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "SqlAtomReader.get_atoms_for_content failed for %s: %s",
                content_id,
                exc,
            )
            return ()


def default_atom_repository() -> SqlAtomRepository:
    from app.database import SessionLocal

    return SqlAtomRepository(SessionLocal)


def default_atom_reader() -> SqlAtomReader:
    from app.database import SessionLocal

    return SqlAtomReader(SessionLocal)


__all__ = [
    "AtomListFilters",
    "SqlAtomReader",
    "SqlAtomRepository",
    "default_atom_reader",
    "default_atom_repository",
]
