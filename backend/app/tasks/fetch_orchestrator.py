"""Non-auth orchestration helpers for fetch tasks."""

from __future__ import annotations

from typing import List

from app.utils.logger import get_logger

logger = get_logger(__name__)


def merge_warning_messages(*messages: str | None) -> str | None:
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
    metadata = dict(source.metadata_ or {})
    metadata["last_fetch_outcome"] = {
        "code": str(code or "unknown"),
        "severity": str(severity or "ok"),
        "message": str(message or ""),
    }
    source.metadata_ = metadata


def persist_fetch_task_exception(source_id: str, exc: Exception) -> None:
    """Best-effort persistence of source error state when task setup fails early."""
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
    except Exception as persist_exc:
        logger.error(f"Failed to persist fetch task exception: {persist_exc}")

