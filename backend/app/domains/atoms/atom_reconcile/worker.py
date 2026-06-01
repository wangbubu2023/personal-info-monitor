"""Async worker: reconcile a newly-extracted atom into the library."""

from __future__ import annotations

import asyncio

from app.ai.provider import ModelProviderClient, get_runtime_from_system_settings
from app.domains.atoms.atom_reconcile.apply import AtomReconcileApplier
from app.domains.atoms.atom_reconcile.candidates import find_reconcile_candidates
from app.domains.atoms.atom_reconcile.prompts import build_reconcile_prompt, parse_reconcile_op
from app.domains.atoms.operations import default_atom_operation_repository
from app.domains.atoms.repository import default_atom_repository
from app.domains.atoms.vocab import AtomOperationType, AtomType
from app.features import atoms_relations_enabled
from app.utils.logger import get_logger

logger = get_logger(__name__)

_RECONCILE_TYPES = {AtomType.INFO, AtomType.DATA}


async def reconcile_atom(atom_id: str) -> bool:
    """Reconcile *atom_id* against existing library atoms. Never raises."""
    if not atoms_relations_enabled():
        return False

    atom_repo = default_atom_repository()
    atom = atom_repo.get_atom(atom_id)
    if atom is None or atom.atom_type not in _RECONCILE_TYPES:
        return False

    from app.database import SessionLocal

    session = SessionLocal()
    try:
        candidates = find_reconcile_candidates(session, atom)
    finally:
        session.close()

    if not candidates:
        return False

    runtime = await get_runtime_from_system_settings(
        setting_key="ai_model",
        default_provider="ollama",
        default_model="",
        default_api_base="http://localhost:11434",
        default_temperature=0.1,
        default_max_tokens=1500,
    )
    if runtime is None:
        return False

    system, user = build_reconcile_prompt(atom, candidates)
    client = ModelProviderClient()
    try:
        raw = await client.generate_text(
            runtime,
            prompt=user,
            system_prompt=system,
            temperature=0.1,
            max_tokens=1500,
            timeout_seconds=90.0,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("reconcile LLM failed for %s: %s", atom_id, exc)
        return False

    op = parse_reconcile_op(raw or "")
    if op is None:
        return False

    applier = AtomReconcileApplier(SessionLocal)
    try:
        result = applier.apply(op, new_atom_id=atom_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("reconcile apply failed for %s: %s", atom_id, exc)
        return False

    try:
        provider = getattr(runtime, "provider", None)
        model = getattr(runtime, "model", None)
        default_atom_operation_repository().record(
            operation_type=AtomOperationType.RECONCILE,
            content_id=atom.content_id,
            atom_id=atom_id,
            related_atom_ids=op.candidate_atom_ids or [c.atom_id for c in candidates],
            model_provider=provider,
            model_name=model,
            prompt=user,
            raw_response=raw,
            parsed={"op": op.op.value, "atom_id": op.atom_id, "result": result},
            reason=op.reason,
        )
    except Exception:  # noqa: BLE001
        pass

    logger.info("reconcile_atom %s → %s", atom_id, op.op.value)
    return bool(result.get("applied"))


def enqueue_reconcile(atom_id: str) -> None:
    """Schedule reconcile on the running loop (no-op if disabled)."""
    if not atoms_relations_enabled():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(reconcile_atom(atom_id))
        return
    task = loop.create_task(reconcile_atom(atom_id))
    task.add_done_callback(
        lambda fut: logger.warning("reconcile task failed for %s: %s", atom_id, fut.exception())
        if fut.exception()
        else None
    )


__all__ = ["enqueue_reconcile", "reconcile_atom"]
