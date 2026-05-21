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
from typing import List, Optional

from sqlalchemy.exc import IntegrityError

from app.domains.enrich.hourly.text_utils import (
    SYSTEM_TZ,
    format_digest_title,
    get_digest_limits,
    get_digest_window_hours,
    local_to_utc_naive,
)
from app.platform.config.system_settings import (
    get_system_settings_sync,
    normalize_hourly_digest_content_types,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


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
            "final_score": content_metadata.get("final_score"),
            "article_score": content_metadata.get("article_score", content_metadata.get("final_score")),
            "lane": content_metadata.get("lane"),
            "selection_status": content_metadata.get("selection_status"),
            "fulltext_status": content_metadata.get("fulltext_status"),
            "score_confidence": content_metadata.get("score_confidence"),
            "source_stars": source_stars,
        })
    return entries, source_names


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
    max_input_items: int,
    content_types: List[str],
):
    from app.models import Content

    types = [t for t in (content_types or []) if t]
    if not types:
        types = ["website", "rss"]
    return (
        db.query(Content)
        .filter(Content.content_type.in_(types))
        .filter(Content.fetched_at >= start_utc)
        .filter(Content.fetched_at < end_utc)
        .order_by(Content.fetched_at.desc())
        .limit(max_input_items)
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


def store_digest(db, digest, title: str, body: str, *, content_count: int, sources: list[str]) -> None:
    """Upsert a digest row, racing safely with a concurrent inserter.

    If a sibling job won the unique-index race we rollback and update
    the row it inserted instead.
    """
    digest.title = title
    digest.summary = body
    digest.content_count = content_count
    digest.sources = sources
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
    digest_limits = get_digest_limits()
    max_input_items = digest_limits["max_input_items"]

    settings = get_system_settings_sync() or {}
    content_types = normalize_hourly_digest_content_types(settings)
    rows = load_digest_rows(
        db,
        start_utc,
        end_utc,
        max_input_items=max_input_items,
        content_types=content_types,
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
            f"过去 {window_hours} 小时内暂无符合所选类型的入库内容。可在设置 → 模型与限制中调整简报扫描类型。",
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
