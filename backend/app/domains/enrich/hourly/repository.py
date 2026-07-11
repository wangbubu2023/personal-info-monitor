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
from datetime import datetime, time, timedelta
from typing import Optional

from sqlalchemy import Float, cast, func
from sqlalchemy.exc import IntegrityError

from app.domains.enrich.hourly.text_utils import (
    format_digest_title,
    get_digest_window_hours,
    local_to_utc_naive,
)
from app.utils.datetime import user_timezone
from app.utils.datetime import to_iso_z
from app.utils.logger import get_logger

logger = get_logger(__name__)

HOURLY_DIGEST_CANDIDATE_LIMIT = 20

_RECENT_EVENT_LOOKBACK_HOURS = 24


def _clamp(value: float, *, min_value: float = 0.0, max_value: float = 100.0) -> float:
    return max(min_value, min(max_value, value))


def _safe_float(value, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _source_key(item: dict) -> str:
    return (
        str(item.get("source_id") or "").strip()
        or str(item.get("source_url") or "").strip()
        or str(item.get("source_name") or "").strip()
        or "unknown"
    )


def _local_digest_label(row) -> datetime:
    return datetime.combine(row.digest_date, time(hour=int(row.hour or 0)), tzinfo=user_timezone())


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


def load_recent_digest_event_index(
    db,
    end_local: datetime,
    *,
    lookback_hours: int = _RECENT_EVENT_LOOKBACK_HOURS,
) -> dict[str, dict]:
    """Return recent stored event metadata keyed by event_key.

    This is intentionally soft state. Older digests will not have event keys,
    and that is fine: first-run behavior simply treats everything as fresh.
    """
    from app.models import HourlyDigest

    start_local = end_local - timedelta(hours=max(1, int(lookback_hours or 1)))
    rows = (
        db.query(HourlyDigest)
        .filter(HourlyDigest.digest_date >= start_local.date())
        .filter(HourlyDigest.digest_date <= end_local.date())
        .all()
    )
    index: dict[str, dict] = {}
    for row in rows:
        label = _local_digest_label(row)
        if label < start_local or label >= end_local:
            continue
        items = row.items_json if isinstance(row.items_json, list) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            event_key = str(item.get("event_key") or "").strip()
            if not event_key:
                continue
            bucket = index.setdefault(
                event_key,
                {
                    "source_keys": set(),
                    "source_names": set(),
                    "content_ids": set(),
                    "last_seen": label,
                    "count": 0,
                },
            )
            bucket["count"] += 1
            bucket["last_seen"] = max(bucket["last_seen"], label)
            for source_key in item.get("source_keys") or []:
                if source_key:
                    bucket["source_keys"].add(str(source_key))
            for source_name in item.get("source_names") or []:
                if source_name:
                    bucket["source_names"].add(str(source_name))
            if item.get("source_name"):
                bucket["source_names"].add(str(item["source_name"]))
            content_id = str(item.get("content_id") or "").strip()
            if content_id:
                bucket["content_ids"].add(content_id)
    return index


def _cluster_confidence(items: list[dict]) -> float:
    if not items:
        return 0.0
    confidences = []
    for item in items:
        meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        raw = item.get("score_confidence", meta.get("score_confidence"))
        if raw is None:
            status = item.get("fulltext_status") or meta.get("fulltext_status")
            raw = {
                "full": 0.92,
                "partial": 0.72,
                "summary_only": 0.48,
                "title_only": 0.22,
                "blocked": 0.0,
            }.get(str(status or "").strip(), 0.6)
        confidences.append(_safe_float(raw, default=0.6))
    return round(_clamp((sum(confidences) / len(confidences)) * 100.0), 1)


def _cluster_incremental_score(cluster: dict, previous: dict | None) -> float:
    items = cluster.get("items") or []
    source_keys = {_source_key(item) for item in items if _source_key(item) != "unknown"}
    if not previous:
        base = 72.0
    else:
        seen_sources = previous.get("source_keys") or set()
        new_sources = source_keys - set(seen_sources)
        base = 25.0 + min(35.0, len(new_sources) * 18.0)
        if not new_sources:
            base -= 12.0
    if len(source_keys) >= 2:
        base += 8.0
    if cluster.get("corroboration_tier") in {"strong", "moderate"}:
        base += 6.0
    if any((item.get("fulltext_status") or (item.get("metadata") or {}).get("fulltext_status")) == "full" for item in items):
        base += 5.0
    return round(_clamp(base), 1)


def _event_section(importance: float, incremental: float, confidence: float, cluster: dict) -> str:
    if importance >= 72 and incremental >= 45 and confidence >= 55:
        return "need_to_know"
    if incremental >= 45 or cluster.get("corroboration_tier") in {"single_low", "single_high"}:
        return "brewing"
    return "later"


def _why_matters(cluster: dict, primary: dict) -> str:
    lane = str(primary.get("lane") or "").strip()
    indep = int(cluster.get("independent_source_count") or 0)
    if indep >= 3:
        return "已有多个独立来源互相确认，优先级上升。"
    if indep == 2:
        return "已有两个独立来源出现相近信号，值得提前留意。"
    if lane in {"must_read", "policy", "ai", "finance"}:
        return "匹配高优先级主题，可能影响后续判断。"
    return "综合评分较高，适合纳入本小时观察。"


def _missing_confirmation(cluster: dict, confidence: float) -> str:
    if confidence < 55:
        return "正文或信源质量还不足，需要更多细节确认。"
    if int(cluster.get("independent_source_count") or 0) < 2:
        return "目前仍偏单源，需要独立来源跟进。"
    return "后续还需要观察是否有一手材料或官方确认。"


def build_hourly_digest_event_briefing_items(
    clusters: list[dict],
    *,
    previous_event_index: dict[str, dict] | None = None,
    limit: int = 12,
) -> list[dict]:
    """Build event-level cards for the redesigned hourly briefing."""
    previous_event_index = previous_event_index or {}
    event_items: list[dict] = []
    for cluster in clusters[: max(0, int(limit or 0))]:
        items = cluster.get("items") or []
        if not items:
            continue
        primary = items[0]
        event_key = str(cluster.get("event_key") or "").strip()
        previous = previous_event_index.get(event_key)
        from app.domains.events.repository import stable_event_id

        event_id = stable_event_id(event_key) if event_key else ""
        importance = round(_clamp(_safe_float(cluster.get("event_score", cluster.get("score")))), 1)
        incremental = _cluster_incremental_score(cluster, previous)
        confidence = _cluster_confidence(items)
        section = _event_section(importance, incremental, confidence, cluster)
        source_names: list[str] = []
        source_keys: list[str] = []
        content_ids: list[str] = []
        for item in items:
            source_name = str(item.get("source_name") or "Unknown").strip()
            if source_name and source_name not in source_names:
                source_names.append(source_name)
            key = _source_key(item)
            if key and key != "unknown" and key not in source_keys:
                source_keys.append(key)
            item_cid = str(item.get("content_id") or "").strip()
            if item_cid and item_cid not in content_ids:
                content_ids.append(item_cid)
        cid = str(primary.get("content_id") or "").strip()
        title = str(primary.get("translated_title") or primary.get("title") or cluster.get("topic") or "").strip()
        summary = str(primary.get("translated_summary") or primary.get("summary") or "").strip()
        if len(summary) > 300:
            summary = f"{summary[:297]}..."
        why_matters = _why_matters(cluster, primary)
        what_changed = summary or "出现新的报道或材料。"
        cluster["incremental_score"] = incremental
        cluster["confidence_score"] = confidence
        cluster["why_matters"] = why_matters
        cluster["what_changed"] = what_changed
        event_items.append(
            {
                "event_key": event_key,
                "event_id": event_id,
                "section": section,
                "content_id": cid,
                "content_ids": content_ids,
                "title": title or "未命名事件",
                "summary": summary or None,
                "what_happened": summary or "本小时出现新的相关信号。",
                "why_matters": why_matters,
                "new_signal": what_changed,
                "missing_confirmation": _missing_confirmation(cluster, confidence),
                "source_name": source_names[0] if source_names else "Unknown",
                "source_names": source_names,
                "source_keys": source_keys,
                "source_url": str(primary.get("source_url") or "") or None,
                "url": str(primary.get("article_url") or ""),
                "local_reader_path": f"/reader/{cid}" if cid else "",
                "publish_time": to_iso_z(primary.get("publish_time")),
                "fetched_at": to_iso_z(primary.get("fetched_at")),
                "score": importance,
                "importance_score": importance,
                "incremental_score": incremental,
                "confidence_score": confidence,
                "lane": primary.get("lane"),
                "duplicate_group_id": (
                    primary.get("metadata", {}).get("duplicate_group_id")
                    if isinstance(primary.get("metadata"), dict)
                    else None
                ),
                "corroboration_tier": cluster.get("corroboration_tier"),
                "independent_source_count": cluster.get("independent_source_count"),
                "is_repeat_event": bool(previous),
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
    from app.domains.ingest.visibility import visible_content_clause
    from app.models import Content

    return (
        db.query(Content)
        .filter(Content.fetched_at >= start_utc)
        .filter(Content.fetched_at < end_utc)
        .filter(visible_content_clause())
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
    now_local = datetime.now(user_timezone())
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
    previous_event_index = load_recent_digest_event_index(db, end_local)

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
        "start_local": start_local,
        "end_local": end_local,
        "previous_event_index": previous_event_index,
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
