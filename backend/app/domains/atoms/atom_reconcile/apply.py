"""Transactional application of reconcile operations."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.domains.atoms.atom_reconcile.types import AtomReconcileOp, ReconcileOpType
from app.domains.atoms.id_gen import next_rel_id
from app.domains.atoms.vocab import AtomStatus, RelationDirection, RelationType
from app.models.atom import Atom, AtomRelation
from app.utils.datetime import utcnow_naive
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _ensure_group(*atoms: Atom) -> str:
    for atom in atoms:
        if atom is not None and atom.reconcile_group_id:
            return atom.reconcile_group_id
    return f"grp-{uuid.uuid4().hex[:12]}"


def _add_flag(atom: Atom, flag: str) -> None:
    flags = list(atom.quality_flags or [])
    if flag not in flags:
        flags.append(flag)
    atom.quality_flags = flags


class AtomReconcileApplier:
    """Apply a reconcile op to the database in a single transaction.

    Operation logging is the caller's responsibility (see worker), so this stays
    a pure DB mutation unit that is easy to unit-test without an LLM.
    """

    def __init__(self, session_factory):
        self._session_factory = session_factory

    def apply(self, op: AtomReconcileOp, *, new_atom_id: str) -> dict:
        session: Session = self._session_factory()
        try:
            new_atom = session.get(Atom, new_atom_id)
            if new_atom is None:
                return {"applied": False, "reason": "new_atom_not_found"}

            target = session.get(Atom, op.atom_id) if op.atom_id else None
            result = self._dispatch(session, op, new_atom, target)
            new_atom.reconcile_reason = op.reason or op.op.value
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _dispatch(self, session: Session, op: AtomReconcileOp, new_atom: Atom, target: Atom | None) -> dict:
        handler = {
            ReconcileOpType.ADD: self._apply_add,
            ReconcileOpType.MERGE: self._apply_merge,
            ReconcileOpType.SUPERSEDE: self._apply_supersede,
            ReconcileOpType.CONTRADICT: self._apply_contradict,
            ReconcileOpType.IGNORE: self._apply_ignore,
        }[op.op]
        return handler(session, new_atom, target)

    @staticmethod
    def _apply_add(session: Session, new_atom: Atom, target: Atom | None) -> dict:
        new_atom.status = AtomStatus.ACTIVE.value
        new_atom.is_latest = True
        return {"applied": True, "op": "ADD", "atom_id": new_atom.atom_id}

    def _apply_merge(self, session: Session, new_atom: Atom, target: Atom | None) -> dict:
        if target is None:
            return self._apply_add(session, new_atom, target)
        group = _ensure_group(new_atom, target)
        new_atom.status = AtomStatus.ACTIVE.value
        new_atom.is_latest = True
        new_atom.reconcile_group_id = group
        new_atom.evidence_count = int(new_atom.evidence_count or 1) + int(target.evidence_count or 1)
        target.status = AtomStatus.SHADOW.value
        target.is_latest = False
        target.reconcile_group_id = group
        _add_flag(target, "merged_into_" + new_atom.atom_id)
        target.updated_at = utcnow_naive()
        return {"applied": True, "op": "MERGE", "atom_id": new_atom.atom_id, "merged": target.atom_id}

    def _apply_supersede(self, session: Session, new_atom: Atom, target: Atom | None) -> dict:
        if target is None:
            return self._apply_add(session, new_atom, target)
        group = _ensure_group(new_atom, target)
        new_atom.status = AtomStatus.ACTIVE.value
        new_atom.is_latest = True
        new_atom.supersedes_atom_id = target.atom_id
        new_atom.reconcile_group_id = group
        target.status = AtomStatus.SUPERSEDED.value
        target.is_latest = False
        target.superseded_by_atom_id = new_atom.atom_id
        target.reconcile_group_id = group
        target.updated_at = utcnow_naive()
        return {"applied": True, "op": "SUPERSEDE", "atom_id": new_atom.atom_id, "superseded": target.atom_id}

    def _apply_contradict(self, session: Session, new_atom: Atom, target: Atom | None) -> dict:
        if target is None:
            return self._apply_add(session, new_atom, target)
        # Both remain consumable; record the contradiction as a relation.
        _add_flag(new_atom, "has_contradiction")
        _add_flag(target, "has_contradiction")
        target.updated_at = utcnow_naive()
        self._upsert_contradiction(session, new_atom.atom_id, target.atom_id)
        return {"applied": True, "op": "CONTRADICT", "atom_id": new_atom.atom_id, "with": target.atom_id}

    @staticmethod
    def _apply_ignore(session: Session, new_atom: Atom, target: Atom | None) -> dict:
        new_atom.status = AtomStatus.SHADOW.value
        new_atom.is_latest = False
        _add_flag(new_atom, "reconcile_ignored")
        return {"applied": True, "op": "IGNORE", "atom_id": new_atom.atom_id}

    @staticmethod
    def _upsert_contradiction(session: Session, atom_a: str, atom_b: str) -> None:
        existing = (
            session.query(AtomRelation)
            .filter(
                ((AtomRelation.atom_a == atom_a) & (AtomRelation.atom_b == atom_b))
                | ((AtomRelation.atom_a == atom_b) & (AtomRelation.atom_b == atom_a))
            )
            .first()
        )
        if existing is not None:
            existing.relation_type = RelationType.CONTRADICTION.value
            existing.direction = RelationDirection.A_TO_B.value
            existing.updated_at = utcnow_naive()
            return
        row = AtomRelation(
            rel_id=next_rel_id(session),
            atom_a=atom_a,
            atom_b=atom_b,
            relation_type=RelationType.CONTRADICTION.value,
            direction=RelationDirection.A_TO_B.value,
            verified=False,
            fact_confidence=0.6,
        )
        session.add(row)


__all__ = ["AtomReconcileApplier"]
