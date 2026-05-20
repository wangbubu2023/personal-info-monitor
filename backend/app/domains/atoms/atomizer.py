"""Idempotent ``atomize_content(content_id)`` extractor.

Phase 6 introduces the structural extraction step that promotes a
finalized ``Content`` row into the optional ``content_atom_bundles``
table. The default extraction is intentionally conservative — a single
heuristic event built from title + publish_time, the source URL host as
a single entity, and an empty relations list — so the table starts
producing data the moment ``ATOMS_ENABLED=true`` is flipped on, without
introducing any new LLM dependency.

Operators or downstream consumers who want richer extraction can swap
:func:`_default_extract` for their own callable; the public entry point
:func:`atomize_content` only cares that the extractor returns three
JSON-serialisable tuples and an optional metadata mapping.

Idempotency is enforced through ``ON CONFLICT (content_id) DO UPDATE``:
calling :func:`atomize_content` repeatedly for the same content_id
overwrites the row instead of creating duplicates.

Failure policy: every exception is logged and swallowed. This module
must never propagate an exception that could block the ingest finalize
path (Phase 6 invariant).
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

from app.database import SessionLocal
from app.domains.atoms.schema import CURRENT_SCHEMA_VERSION
from app.features import atoms_enabled
from app.models import Content, ContentAtomBundle
from app.utils.datetime import utcnow_naive
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _default_extract(content: Content) -> tuple[
    tuple[Mapping[str, Any], ...],
    tuple[Mapping[str, Any], ...],
    tuple[Mapping[str, Any], ...],
    Mapping[str, Any],
]:
    """Heuristic extractor — title + publish_time as a single event, host as one entity.

    Returns ``(events, entities, relations, metadata)`` tuples ready to
    be stored in the bundle row. Designed to be deterministic and
    side-effect free so repeated calls produce equivalent payloads.
    """
    events: list[Mapping[str, Any]] = []
    entities: list[Mapping[str, Any]] = []
    relations: list[Mapping[str, Any]] = []

    title = (content.title or "").strip()
    publish_time = content.publish_time or content.fetched_at
    if title:
        events.append(
            {
                "kind": "headline",
                "title": title,
                "occurred_at": publish_time.isoformat() if publish_time else None,
            }
        )

    host = ""
    try:
        host = (urlparse(content.original_url or "").hostname or "").lower()
    except ValueError:
        host = ""
    if host:
        entities.append({"kind": "host", "value": host})

    metadata: Mapping[str, Any] = {
        "extractor": "default-heuristic",
        "extractor_version": 1,
    }
    return tuple(events), tuple(entities), tuple(relations), metadata


def _serialise(items: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [dict(item) for item in items]


def atomize_content(content_id: str) -> bool:
    """Idempotently atomise one Content row.

    Returns ``True`` when a bundle was written / refreshed, ``False`` if
    the atoms feature is disabled, the content row is missing, or an
    exception was caught. *Never* raises — failures must not block
    ingest finalization.
    """
    if not atoms_enabled():
        return False

    db = SessionLocal()
    try:
        content = db.query(Content).filter(Content.id == content_id).first()
        if content is None:
            logger.debug("atomize_content: content %s not found; skipping", content_id)
            return False

        events, entities, relations, extra_metadata = _default_extract(content)

        existing = (
            db.query(ContentAtomBundle)
            .filter(ContentAtomBundle.content_id == content_id)
            .first()
        )
        if existing is None:
            bundle = ContentAtomBundle(
                content_id=content_id,
                schema_version=CURRENT_SCHEMA_VERSION,
                events=_serialise(events),
                entities=_serialise(entities),
                relations=_serialise(relations),
                bundle_metadata=dict(extra_metadata),
            )
            db.add(bundle)
        else:
            existing.schema_version = CURRENT_SCHEMA_VERSION
            existing.events = _serialise(events)
            existing.entities = _serialise(entities)
            existing.relations = _serialise(relations)
            existing.bundle_metadata = dict(extra_metadata)
            existing.updated_at = utcnow_naive()
        db.commit()
        return True

    except Exception as exc:  # noqa: BLE001 - Phase 6 invariant: never propagate
        logger.warning("atomize_content failed for %s: %s", content_id, exc)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001 - rollback best-effort
            pass
        return False
    finally:
        db.close()


__all__ = ["atomize_content"]
