"""SQLAlchemy repository for the knowledge-entity layer."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import distinct, func
from sqlalchemy.orm import Session

from app.domains.atoms.entities.extract import EntityMention, extract_entity_mentions
from app.domains.atoms.id_gen import next_entity_id
from app.domains.atoms.types import AtomRecord
from app.models.atom_event import AtomEntity, EntityAlias, KnowledgeEntity
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class EntityRecord:
    entity_id: str
    canonical_name: str
    entity_type: str


class SqlEntityRepository:
    def __init__(self, session_factory):
        self._session_factory = session_factory

    def upsert_entity(self, name: str, entity_type: str, *, source: str | None = None) -> EntityRecord:
        session: Session = self._session_factory()
        try:
            record = self._upsert_entity_in_session(session, name, entity_type, source=source)
            session.commit()
            return record
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _upsert_entity_in_session(
        self,
        session: Session,
        name: str,
        entity_type: str,
        *,
        source: str | None = None,
    ) -> EntityRecord:
        # Resolve via alias first so variant spellings collapse to one entity.
        alias_row = (
            session.query(EntityAlias).filter(EntityAlias.alias == name).first()
        )
        if alias_row is not None:
            entity = session.get(KnowledgeEntity, alias_row.entity_id)
            if entity is not None:
                return EntityRecord(entity.entity_id, entity.canonical_name, entity.entity_type)

        entity = (
            session.query(KnowledgeEntity)
            .filter(
                KnowledgeEntity.canonical_name == name,
                KnowledgeEntity.entity_type == entity_type,
            )
            .first()
        )
        if entity is None:
            entity = KnowledgeEntity(
                entity_id=next_entity_id(session),
                canonical_name=name,
                entity_type=entity_type,
            )
            session.add(entity)
            session.flush()
            session.add(EntityAlias(alias=name, entity_id=entity.entity_id, source=source))
            session.flush()
        return EntityRecord(entity.entity_id, entity.canonical_name, entity.entity_type)

    def link_atom_entities(self, atom: AtomRecord, mentions: list[EntityMention] | None = None) -> int:
        """Upsert entities for *atom* and link them. Returns number of links created."""
        mentions = mentions if mentions is not None else extract_entity_mentions(atom)
        if not mentions:
            return 0
        session: Session = self._session_factory()
        created = 0
        try:
            for mention in mentions:
                entity = self._upsert_entity_in_session(
                    session, mention.name, mention.entity_type, source="atom_payload"
                )
                exists = (
                    session.query(AtomEntity)
                    .filter(
                        AtomEntity.atom_id == atom.atom_id,
                        AtomEntity.entity_id == entity.entity_id,
                        AtomEntity.role == mention.role,
                    )
                    .first()
                )
                if exists is None:
                    session.add(
                        AtomEntity(
                            atom_id=atom.atom_id,
                            entity_id=entity.entity_id,
                            role=mention.role,
                        )
                    )
                    created += 1
            session.commit()
            return created
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def list_entities(self, *, entity_type: str | None = None, search: str | None = None, limit: int = 50) -> list[dict]:
        session: Session = self._session_factory()
        try:
            query = session.query(KnowledgeEntity)
            if entity_type:
                query = query.filter(KnowledgeEntity.entity_type == entity_type)
            if search:
                query = query.filter(KnowledgeEntity.canonical_name.like(f"%{search.strip()}%"))
            rows = query.order_by(KnowledgeEntity.canonical_name.asc()).limit(max(1, limit)).all()
            out: list[dict] = []
            for row in rows:
                count = (
                    session.query(func.count(distinct(AtomEntity.atom_id)))
                    .filter(AtomEntity.entity_id == row.entity_id)
                    .scalar()
                ) or 0
                out.append(
                    {
                        "entity_id": row.entity_id,
                        "canonical_name": row.canonical_name,
                        "entity_type": row.entity_type,
                        "atom_count": int(count),
                    }
                )
            return out
        finally:
            session.close()

    def list_atoms_for_entity(self, entity_id: str) -> list[str]:
        session: Session = self._session_factory()
        try:
            rows = (
                session.query(AtomEntity.atom_id)
                .filter(AtomEntity.entity_id == entity_id)
                .distinct()
                .all()
            )
            return [r[0] for r in rows]
        finally:
            session.close()


def default_entity_repository() -> SqlEntityRepository:
    from app.database import SessionLocal

    return SqlEntityRepository(SessionLocal)


__all__ = ["EntityRecord", "SqlEntityRepository", "default_entity_repository"]
