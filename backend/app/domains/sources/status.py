"""Source status helpers: outcome bookkeeping + warning merging.

These three helpers cluster around "what does the next call to the status
API need to know about this source": ``set_last_fetch_outcome`` writes a
structured outcome into ``Source.metadata_['last_fetch_outcome']``;
``merge_warning_messages`` collapses several non-fatal collector
warnings into a single line; ``persist_fetch_task_exception`` is the
last-ditch error sink when even the fetch task setup fails.

Phase 1 of the refactor (§7 step 7) moved them out of
``app.tasks.fetch_orchestrator``; that module now re-exports the names
for one cycle so legacy patch targets keep working.
"""

from __future__ import annotations

from typing import List

from app.utils.logger import get_logger

logger = get_logger(__name__)


def merge_warning_messages(*messages: str | None) -> str | None:
    """Collapse heterogenous warning strings into a single deduplicated line.

    The joining separator is the full-width Chinese semicolon (``；``)
    because the resulting message is displayed verbatim in the source
    list UI. Returning ``None`` instead of an empty string lets the
    caller distinguish "no warning" from "empty warning".
    """
    normalized: List[str] = []
    seen = set()
    for message in messages:
        text = str(message or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    if not normalized:
        return None
    return "；".join(normalized)


def set_last_fetch_outcome(source, code: str, severity: str, message: str) -> None:
    """Stamp ``source.metadata_['last_fetch_outcome']`` with a structured outcome.

    Mutates ``source.metadata_`` **in place** (re-assigning a dict copy)
    so SQLAlchemy's JSON change tracking picks the update up.
    """
    metadata = dict(source.metadata_ or {})
    metadata["last_fetch_outcome"] = {
        "code": str(code or "unknown"),
        "severity": str(severity or "ok"),
        "message": str(message or ""),
    }
    source.metadata_ = metadata


def persist_fetch_task_exception(source_id: str, exc: Exception) -> None:
    """Best-effort persistence of source error state when task setup fails early.

    Wraps the entire write in a broad ``except`` because this runs from
    the outermost fetch task ``except`` branch — if we cannot even log
    the error we don't want to escalate further and mask the original
    exception.
    """
    try:
        from app.database import SessionLocal
        from app.models import Source

        db = SessionLocal()
        try:
            source = db.query(Source).filter(Source.id == source_id).first()
            if not source:
                return
            source.error_count = (source.error_count or 0) + 1
            source.last_error = str(exc)
            db.commit()
        finally:
            db.close()
    except Exception as persist_exc:  # noqa: BLE001 — last-ditch error sink
        logger.error(f"Failed to persist fetch task exception: {persist_exc}")


__all__ = [
    "merge_warning_messages",
    "set_last_fetch_outcome",
    "persist_fetch_task_exception",
]
