"""Persistence / windowing layer for the hourly digest generator.

Owns all DB-facing helpers used by the orchestrator:

- computing the ``(now - 1h, now)`` local / UTC window,
- loading candidate rows,
- idempotently upserting :class:`HourlyDigest` rows,
- shaping raw ORM objects into the ``entry`` dicts consumed by the
  ranking / selection / synthesis layers.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import Float, cast, func
from sqlalchemy.exc import IntegrityError

from app.domains.enrich.hourly.text_utils import (
    SYSTEM_TZ,
    format_digest_title,
    get_digest_window_hours,
    local_to_utc_naive,
)
from app.utils.datetime import to_iso_z
from app.utils.logger import get_logger

logger = get_logger(__name__)

HOURLY_DIGEST_CANDIDATE_LIMIT = 20


def candidate_score_expr(content_model):
    """Score used to pick hourly digest candidates.

    ``final_score`` is the release-facing aggregate. Some older rows only have
    ``article_score``, so keep it as a compatibility fallback and put unscored
    rows last.
    """
    return func.coalesce(
        content_model.final_score,
        content_model.article_score,
        cast(func.json_extract(content_model.metadata_, "$.final_score"), Float),
        cast(func.json_extract(content_model.metadata_, "$.article_score"), Float),
        -1.0,
    )


def candidate_ordering(content_model):
    """Order newest-window candidates by score, then deterministic freshness."""
    return (
        candidate_score_expr(content_model).desc(),
        content_model.fetched_at.desc(),
        content_model.publish_time.desc().nulls_last(),
    )


def build_digest_text_seed(content) -> str:
    """Pick a usable text seed for ranking/LLM input from a Content row.

    Paywalled rows that we *did* authenticate for get a bigger budget
    (2000 chars) because the full text is often the only way to cluster
    them accurately. Unauthenticated rows stay at 1500 to keep the
    combined prompt within model limits.
    """
    source = content.source
    has_paywall_auth = bool(source and (source.auth_required or source.auth_config_id))
    full_content = (content.full_content or "").strip()
    if has_paywall_auth and full_content:
        return full_content[:2000]
    if full_content:
        return full_content[:1500]
    return (content.translated_summary or content.summary or "").strip()


def build_entries(rows: list) -> tuple[list[dict], list[str]]:
    entries: list[dict] = []
    source_names: list[str] = []
    for c in rows:
        source_name = c.source.name if c.source else "Unknown"
        if source_name not in source_names:
            source_names.append(source_name)
        seed_text = build_digest_text_seed(c)
        content_metadata = c.metadata_ if isinstance(c.metadata_, dict) else {}
        source_metadata = (
            c.source.metadata_
            if c.source and isinstance(c.source.metadata_, dict)
            else {}
        )
        source_stars = content_metadata.get("source_stars") or source_metadata.get("source_stars")
        entries.append({
            "content_id": str(c.id),
            "source_id": str(c.source_id) if c.source_id else "",
            "source_name": source_name,
            "source_url": (c.source.url if c.source else "") or c.original_url or "",
            "article_url": c.original_url or "",
            "title": c.title or "",
            "original_title": c.title or "",
            "summary": seed_text,
            "translated_title": getattr(c, "translated_title", None) or "",
            "translated_summary": getattr(c, "translated_summary", None) or "",
            "publish_time": c.publish_time,
            "fetched_at": c.fetched_at,
            "metadata": content_metadata,
            "source_metadata": source_metadata,
            "final_score": c.final_score if c.final_score is not None else content_metadata.get("final_score"),
            "article_score": c.article_score
            if c.article_score is not None
            else content_metadata.get("article_score", content_metadata.get("final_score")),
            "lane": c.lane or content_metadata.get("lane"),
            "selection_status": c.selection_status or content_metadata.get("selection_status"),
            "fulltext_status": content_metadata.get("fulltext_status"),
            "score_confidence": content_metadata.get("score_confidence"),
            "source_stars": source_stars,
        })
    return entries, source_names


def build_hourly_digest_event_items(entries: list[dict], *, limit: int = 8) -> list[dict]:
    """Build a compact structured snapshot for event-card rendering."""
    event_items: list[dict] = []
    for entry in entries[: max(0, int(limit or 0))]:
        metadata = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
        score = entry.get("final_score")
        if score is None:
            score = entry.get("article_score")
        try:
            score = float(score) if score is not None else None
        except (TypeError, ValueError):
            score = None
        event_items.append(
            {
                "content_id": str(entry.get("content_id") or ""),
                "title": str(entry.get("translated_title") or entry.get("title") or "").strip(),
                "summary": str(entry.get("translated_summary") or entry.get("summary") or "").strip()[:300] or None,
                "source_name": str(entry.get("source_name") or "Unknown"),
                "source_url": str(entry.get("source_url") or "") or None,
                "url": str(entry.get("article_url") or ""),
                "publish_time": to_iso_z(entry.get("publish_time")),
                "fetched_at": to_iso_z(entry.get("fetched_at")),
                "score": score,
                "lane": entry.get("lane"),
                "duplicate_group_id": metadata.get("duplicate_group_id"),
            }
        )
    return event_items


def compute_digest_window(now_local: datetime, *, window_hours: int = 1) -> tuple[datetime, datetime, datetime, datetime]:
    """Return ``(start_local, end_local, start_utc, end_utc)`` for the previous window.

    The window always aligns to completed hour boundaries. For ``window_hours=1``,
    a scheduler firing at 19:20 writes the ``18:00 → 19:00`` digest. For
    ``window_hours=3``, the same 19:20 catch-up writes ``15:00 → 18:00``.
    """
    window_hours = max(1, int(window_hours or 1))
    floored = now_local.replace(minute=0, second=0, microsecond=0)
    if window_hours <= 1:
        end_local = floored
    else:
        end_hour = (floored.hour // window_hours) * window_hours
        end_local = floored.replace(hour=end_hour)
    start_local = end_local - timedelta(hours=window_hours)
    start_utc = local_to_utc_naive(start_local)
    end_utc = local_to_utc_naive(end_local)
    return start_local, end_local, start_utc, end_utc


def load_digest_rows(
    db,
    start_utc: datetime,
    end_utc: datetime,
    *,
    candidate_limit: int = HOURLY_DIGEST_CANDIDATE_LIMIT,
):
    from app.models import Content

    return (
        db.query(Content)
        .filter(Content.fetched_at >= start_utc)
        .filter(Content.fetched_at < end_utc)
        .order_by(*candidate_ordering(Content))
        .limit(max(1, int(candidate_limit or HOURLY_DIGEST_CANDIDATE_LIMIT)))
        .all()
    )


def get_or_create_hourly_digest(db, digest_date, digest_hour: int, title: str):
    from app.models import HourlyDigest

    digest = (
        db.query(HourlyDigest)
        .filter(HourlyDigest.digest_date == digest_date, HourlyDigest.hour == digest_hour)
        .first()
    )
    if not digest:
        digest = HourlyDigest(digest_date=digest_date, hour=digest_hour, title=title)
        db.add(digest)
    return digest


def store_digest(
    db,
    digest,
    title: str,
    body: str,
    *,
    content_count: int,
    sources: list[str],
    items_json: list[dict] | None = None,
) -> None:
    """Upsert a digest row, racing safely with a concurrent inserter.

    If a sibling job won the unique-index race we rollback and update
    the row it inserted instead.
    """
    digest.title = title
    digest.summary = body
    digest.content_count = content_count
    digest.sources = sources
    digest.items_json = items_json or []
    try:
        db.commit()
        return
    except IntegrityError:
        db.rollback()

    from app.models import HourlyDigest

    existing = (
        db.query(HourlyDigest)
        .filter(HourlyDigest.digest_date == digest.digest_date, HourlyDigest.hour == digest.hour)
        .first()
    )
    if not existing:
        raise

    existing.title = title
    existing.summary = body
    existing.content_count = content_count
    existing.sources = sources
    existing.items_json = items_json or []
    db.commit()


def store_empty_digest(
    db, digest, title: str, message: str, *, content_count: int, sources: list[str]
) -> None:
    store_digest(
        db,
        digest,
        title,
        f"## {title}\n\n### 重点\n{message}",
        content_count=content_count,
        sources=sources,
        items_json=[],
    )


def build_digest_generation_context(db) -> Optional[dict]:
    """Load the previous hour's rows, upsert an empty digest when idle.

    Returns ``None`` when nothing was ingested (an empty-state digest
    is persisted as a side effect), or a context dict the orchestrator
    passes to the selection/synthesis layers otherwise.
    """
    now_local = datetime.now(SYSTEM_TZ)
    window_hours = get_digest_window_hours()
    start_local, end_local, start_utc, end_utc = compute_digest_window(
        now_local,
        window_hours=window_hours,
    )
    rows = load_digest_rows(
        db,
        start_utc,
        end_utc,
        candidate_limit=HOURLY_DIGEST_CANDIDATE_LIMIT,
    )
    digest_date = end_local.date()
    digest_hour = end_local.hour
    title = format_digest_title(end_local, window_hours=window_hours)
    digest = get_or_create_hourly_digest(db, digest_date, digest_hour, title)

    if not rows:
        store_empty_digest(
            db,
            digest,
            title,
            f"过去 {window_hours} 小时内暂无新增入库内容。",
            content_count=0,
            sources=[],
        )
        return None

    entries, source_names = build_entries(rows)

    return {
        "db": db,
        "digest": digest,
        "title": title,
        "rows": rows,
        "source_names": source_names,
        "entries": entries,
        "window_hours": window_hours,
    }


async def clear_hourly_digests() -> None:
    """Delete all stored hourly digests (admin-triggered reset)."""

    def _clear():
        from app.database import SessionLocal
        from app.models import HourlyDigest

        db = SessionLocal()
        try:
            deleted = db.query(HourlyDigest).delete()
            db.commit()
            logger.info("Cleared %d hourly digests", deleted)
        finally:
            db.close()

    await asyncio.to_thread(_clear)
