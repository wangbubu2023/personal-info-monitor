"""Async worker: infer cross-article relations for a single atom."""

from __future__ import annotations

import asyncio

from app.domains.atoms.relation_infer.candidates import find_candidates
from app.domains.atoms.relation_infer.llm_judge import judge_relation_pair
from app.domains.atoms.relations_repository import default_atom_relations_repository
from app.domains.atoms.repository import default_atom_repository
from app.domains.atoms.vocab import AtomType
from app.features import atoms_relations_enabled
from app.utils.logger import get_logger

logger = get_logger(__name__)

MAX_NEW_RELATIONS = 5
_INFER_TYPES = {AtomType.INFO, AtomType.DATA}


async def infer_relations(atom_id: str) -> int:
    """Infer up to :data:`MAX_NEW_RELATIONS` relations for *atom_id*. Never raises."""
    if not atoms_relations_enabled():
        return 0

    atom_repo = default_atom_repository()
    rel_repo = default_atom_relations_repository()
    atom = atom_repo.get_atom(atom_id)
    if atom is None or atom.atom_type not in _INFER_TYPES:
        return 0

    from app.database import SessionLocal

    session = SessionLocal()
    try:
        candidates = find_candidates(session, atom)
    finally:
        session.close()

    if not candidates:
        return 0

    existing = rel_repo.list_relations_for_atom(atom_id)
    existing_pairs = {(rel.atom_a, rel.atom_b) for rel in existing}
    created = 0

    for candidate in candidates:
        if created >= MAX_NEW_RELATIONS:
            break
        pair = (atom_id, candidate.atom_id)
        if pair in existing_pairs:
            continue

        try:
            relation = await judge_relation_pair(atom, candidate)
        except Exception as exc:  # noqa: BLE001
            logger.warning("infer_relations judge failed %s↔%s: %s", atom_id, candidate.atom_id, exc)
            continue

        if relation is None:
            continue

        rel_repo.upsert_relation(relation)
        existing_pairs.add(pair)
        created += 1
        logger.info(
            "infer_relations: %s ↔ %s → %s",
            atom_id,
            candidate.atom_id,
            relation.relation_type.value,
        )

    return created


def enqueue_relation_infer(atom_id: str) -> None:
    """Schedule relation inference on the running event loop (no-op if disabled)."""
    if not atoms_relations_enabled():
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(infer_relations(atom_id))
        return

    task = loop.create_task(infer_relations(atom_id))
    task.add_done_callback(
        lambda fut: logger.warning(
            "infer_relations task failed for %s: %s",
            atom_id,
            fut.exception(),
        )
        if fut.exception()
        else None
    )


__all__ = ["MAX_NEW_RELATIONS", "enqueue_relation_infer", "infer_relations"]
