"""Idempotent LLM atom extraction for Content rows."""

from __future__ import annotations

from sqlalchemy.orm import joinedload

from app.database import SessionLocal
from app.domains.atoms.extractor.pipeline import extract_atoms_from_content
from app.domains.atoms.atom_reconcile.worker import enqueue_reconcile
from app.domains.atoms.knowledge import link_atom_knowledge
from app.domains.atoms.operations import default_atom_operation_repository
from app.domains.atoms.relation_infer.worker import enqueue_relation_infer
from app.domains.atoms.repository import default_atom_repository
from app.domains.atoms.vocab import AtomOperationType, AtomType
from app.features import (
    atoms_enabled,
    atoms_knowledge_enabled,
    atoms_reconcile_enabled,
    atoms_relations_enabled,
)
from app.models import Content
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def atomize_content_async(content_id: str) -> bool:
    """Extract atoms via LLM and upsert into ``atoms`` table. Never raises."""
    if not atoms_enabled():
        return False

    db = SessionLocal()
    try:
        content = (
            db.query(Content)
            .options(joinedload(Content.source))
            .filter(Content.id == content_id)
            .first()
        )
        if content is None:
            logger.debug("atomize_content: content %s not found; skipping", content_id)
            return False

        atoms, meta = await extract_atoms_from_content(content)
        repo = default_atom_repository()
        upserted = repo.upsert_atoms_for_content(content_id, atoms)

        try:
            model = meta.get("llm_model") or ""
            provider, _, model_name = model.partition(":")
            default_atom_operation_repository().record(
                operation_type=AtomOperationType.EXTRACT,
                content_id=content_id,
                related_atom_ids=[r.atom_id for r in upserted],
                model_provider=provider or None,
                model_name=model_name or None,
                parsed=meta,
                reason=meta.get("skipped_reason") or "extraction_run",
            )
        except Exception:  # noqa: BLE001
            pass

        reconcile_on = atoms_reconcile_enabled()
        relations_on = atoms_relations_enabled()
        knowledge_on = atoms_knowledge_enabled()
        if reconcile_on or relations_on or knowledge_on:
            for record in upserted:
                if record.atom_type not in (AtomType.INFO, AtomType.DATA):
                    continue
                if reconcile_on:
                    enqueue_reconcile(record.atom_id)
                elif relations_on:
                    enqueue_relation_infer(record.atom_id)
                if knowledge_on:
                    link_atom_knowledge(record)

        content_meta = dict(content.metadata_ or {})
        content_meta["atoms"] = meta
        content.metadata_ = content_meta
        db.commit()

        logger.info(
            "atomize_content: %s → %d atoms (sentences=%s model=%s)",
            content_id,
            meta.get("atom_count", 0),
            meta.get("sentence_count"),
            meta.get("llm_model"),
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("atomize_content failed for %s: %s", content_id, exc)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return False
    finally:
        db.close()


def atomize_content(content_id: str) -> bool:
    """Sync wrapper for ingest sidecar — schedules async extract on running loop."""
    import asyncio

    if not atoms_enabled():
        return False
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(atomize_content_async(content_id))

    future = asyncio.ensure_future(atomize_content_async(content_id))
    future.add_done_callback(
        lambda f: logger.warning(
            "atomize_content async task failed for %s: %s",
            content_id,
            f.exception(),
        )
        if f.exception()
        else None
    )
    return True


__all__ = ["atomize_content", "atomize_content_async"]
