"""Rule-based L3/L5 enrichment for a freshly-stored atom.

Links entities (L5) and assigns the atom to an event cluster (L3). Pure SQL +
rules, no LLM, so it is cheap enough to run inline after extraction.
"""

from __future__ import annotations

from app.domains.atoms.entities.repository import default_entity_repository
from app.domains.atoms.events.clustering import assign_atom_to_cluster
from app.domains.atoms.types import AtomRecord
from app.features import atoms_knowledge_enabled
from app.utils.logger import get_logger

logger = get_logger(__name__)


def link_atom_knowledge(atom: AtomRecord) -> None:
    """Link entities and assign an event cluster for *atom*. Never raises."""
    if not atoms_knowledge_enabled():
        return
    try:
        default_entity_repository().link_atom_entities(atom)
    except Exception as exc:  # noqa: BLE001
        logger.warning("entity linking failed for %s: %s", atom.atom_id, exc)

    try:
        from app.database import SessionLocal

        session = SessionLocal()
        try:
            assign_atom_to_cluster(session, atom)
        finally:
            session.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("event clustering failed for %s: %s", atom.atom_id, exc)


__all__ = ["link_atom_knowledge"]
