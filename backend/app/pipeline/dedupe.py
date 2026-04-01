"""Deduplication helpers for fetch pipeline normalization."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Content, Source
from app.utils.datetime import utcnow_naive
from app.utils.text import truncate_content
from app.utils.logger import get_logger

logger = get_logger(__name__)


def handle_external_id_duplicate(
    db: Session,
    source: Source,
    raw_content: dict,
    external_id: str,
) -> bool:
    """Handle duplicate external_id detection.

    Returns True when the incoming row should be skipped (same-source duplicate).
    Cross-source matches are recorded in metadata but preserved.
    """
    existing = db.query(Content).filter(
        Content.source_id == source.id,
        Content.external_id == external_id,
    ).first()

    cross_source_match = (
        db.query(Content.id)
        .join(Source)
        .filter(
            Source.type == source.type,
            Content.external_id == external_id,
            Content.source_id != source.id,
        )
        .first()
    )
    if cross_source_match:
        raw_meta = raw_content.get("metadata") if isinstance(raw_content.get("metadata"), dict) else {}
        merged = dict(raw_meta)
        merged["cross_source_external_id_match"] = str(cross_source_match[0])
        raw_content["metadata"] = merged

    if not existing:
        return False

    logger.info("Skipping duplicate content (same-source external_id): %s", external_id)
    raw_meta = raw_content.get("metadata") if isinstance(raw_content.get("metadata"), dict) else {}
    raw_text = str(raw_content.get("content") or "").strip()
    article_fulltext = bool(raw_meta.get("article_fulltext"))

    # Backfill richer payload to existing rows when this fetch has a better body.
    if raw_meta:
        merged_meta = existing.metadata_ if isinstance(existing.metadata_, dict) else {}
        merged_meta = {**merged_meta, **raw_meta}
        existing.metadata_ = merged_meta

    if article_fulltext and raw_text and len(raw_text) >= 280:
        should_upgrade = not existing.full_content or len(raw_text) > len(existing.full_content or "")
        if should_upgrade:
            existing.full_content = truncate_content(raw_text, url=str(raw_content.get("url") or ""))
            if not existing.summary:
                existing.summary = raw_text[:300] + ("..." if len(raw_text) > 300 else "")
            if raw_content.get("url"):
                existing.original_url = str(raw_content.get("url"))
            if str(existing.title or "").startswith(("http://", "https://")) and raw_content.get("title"):
                existing.title = str(raw_content.get("title"))
            existing.updated_at = utcnow_naive()
            logger.info("Backfilled article fulltext for duplicate content: %s", external_id)

    db.commit()
    return True
