# backend/app/api/sources/_helpers.py
"""Private helper functions shared across sources sub-modules."""

from typing import Dict, List, Optional, Tuple
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Source, AuthConfig
from app.models.source import SourceType
from app.features import PODCAST_DISABLED_DETAIL, PODCAST_SOURCES_ENABLED
from app.services.system_settings import get_system_settings_async
from app.utils.datetime import to_iso_z
from app.utils.ttl_cache import TTLCache
from app.utils.url import host_matches, normalize_host
from app.utils.logger import get_logger

logger = get_logger(__name__)

MAX_SOURCES_PAGE_SIZE = 200

_source_cache = TTLCache(ttl_seconds=30)


def _source_type_value(source_type: object) -> str:
    return source_type.value if hasattr(source_type, "value") else str(source_type)


def _ensure_supported_source_type(source_type: object) -> str:
    normalized = _source_type_value(source_type)
    if normalized == "podcast" and not PODCAST_SOURCES_ENABLED:
        raise HTTPException(status_code=409, detail=PODCAST_DISABLED_DETAIL)
    return normalized


def _exclude_disabled_source_types(query):
    if not PODCAST_SOURCES_ENABLED:
        query = query.filter(Source.type != SourceType.PODCAST)
    return query


def _source_is_visible(source: Source) -> bool:
    return PODCAST_SOURCES_ENABLED or _source_type_value(source.type) != "podcast"


def _invalidate_source_cache() -> None:
    _source_cache.invalidate()


def _coerce_limit_int(value, default: int, *, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        return default
    return max(min_value, min(max_value, parsed))


async def _resolve_max_sources_limit(db: AsyncSession) -> int:
    import app.api.sources as _pkg
    _gssa = getattr(_pkg, "get_system_settings_async", get_system_settings_async)
    settings = await _gssa(db)
    limits = settings.get("limits") if isinstance(settings, dict) else {}
    limits = limits if isinstance(limits, dict) else {}
    return _coerce_limit_int(limits.get("max_sources"), 200, min_value=1, max_value=5000)


async def _ensure_source_quota(db: AsyncSession, incoming_count: int = 1) -> None:
    incoming = max(0, int(incoming_count or 0))
    if incoming <= 0:
        return
    max_sources = await _resolve_max_sources_limit(db)
    total_result = await db.execute(select(func.count(Source.id)))
    current_total = int(total_result.scalar() or 0)
    if current_total + incoming > max_sources:
        raise HTTPException(status_code=409, detail="监控源数量已达到上限，无法继续添加。")


def _normalize_extra_urls(extra_urls: Optional[List[str]]) -> List[str]:
    if not extra_urls:
        return []
    seen = set()
    normalized: List[str] = []
    for raw in extra_urls:
        if not raw:
            continue
        candidate = raw.strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        normalized.append(candidate)
    return normalized


def _get_source_urls(source: Source) -> List[str]:
    metadata = source.metadata_ if isinstance(source.metadata_, dict) else {}
    extras = _normalize_extra_urls(metadata.get("extra_urls"))
    urls = [source.url]
    for u in extras:
        if u != source.url:
            urls.append(u)
    return urls


def _pick_best_probe(results: List[Tuple[str, object]]) -> Tuple[object, Dict[str, str], int]:
    rss_urls: Dict[str, str] = {}
    ok_count = 0
    status_order = {"ok": 0, "warning": 1, "error": 2, "unknown": 3}
    best_url = ""
    best_result = None
    best_rank = 99
    for url, result in results:
        status = getattr(result, "status", "unknown")
        rank = status_order.get(status, 3)
        if getattr(result, "rss_url", None):
            rss_urls[url] = result.rss_url
        if status == "ok":
            ok_count += 1
        if best_result is None or rank < best_rank:
            best_result = result
            best_rank = rank
            best_url = url
    if best_result is not None:
        source_message = getattr(best_result, "message", "") or ""
        summary = f"可用 URL {ok_count}/{len(results)}"
        best_result.message = f"{summary}；主策略来自 {best_url}。{source_message}".strip("。")
    return best_result, rss_urls, ok_count


async def _find_matching_auth_config_id(db: AsyncSession, url: str) -> Optional[UUID]:
    source_host = normalize_host(url)
    if not source_host:
        return None
    result = await db.execute(select(AuthConfig).order_by(AuthConfig.updated_at.desc()))
    configs = result.scalars().all()
    for cfg in configs:
        cfg_host = normalize_host(cfg.site_url)
        if host_matches(source_host, cfg_host):
            return cfg.id
    return None


async def _probe_urls(urls: List[str], source_type: str):
    import asyncio
    from app.services.probe_service import ProbeService
    _probe_service = ProbeService()
    tasks = [_probe_service.probe(url, source_type) for url in urls]
    probe_results = await asyncio.gather(*tasks, return_exceptions=True)
    paired = [(url, r) for url, r in zip(urls, probe_results) if not isinstance(r, Exception)]
    if not paired:
        fallback = await _probe_service.probe(urls[0], source_type)
        return fallback, {}, 0
    return _pick_best_probe(paired)


def _compute_fetch_status(s: Source, probe: dict) -> tuple:
    probe_status = probe.get("status", "unknown")
    probe_strategy = probe.get("strategy", "unknown")
    probe_message = probe.get("message", "")
    metadata = s.metadata_ if isinstance(s.metadata_, dict) else {}
    outcome = metadata.get("last_fetch_outcome") if isinstance(metadata.get("last_fetch_outcome"), dict) else {}
    outcome_severity = str(outcome.get("severity") or "").strip().lower()
    outcome_message = str(outcome.get("message") or "").strip()
    has_content = bool(s.last_content_id)
    has_fetched = s.last_fetched_at is not None
    has_errors = s.error_count > 0 and s.last_error
    if has_fetched and outcome_severity == "error":
        return ("error", probe_strategy if probe_strategy != "unknown" else "auto", outcome_message or "最近抓取失败")
    if has_fetched and outcome_severity == "warning":
        return ("warning", probe_strategy if probe_strategy != "unknown" else "auto", outcome_message or "最近抓取部分受限")
    if has_content and has_fetched:
        if has_errors:
            return ("warning", probe_strategy if probe_strategy != "unknown" else "auto",
                    f"已成功抓取过内容，但最近有错误: {s.last_error[:60] if s.last_error else ''}")
        return ("ok", probe_strategy if probe_strategy != "unknown" else "auto", "已成功抓取内容")
    if has_fetched and not has_content:
        if probe_status == "ok":
            return ("ok", probe_strategy, f"探测可用。{probe_message}")
        if has_errors:
            return ("error", probe_strategy, f"抓取失败: {s.last_error[:60] if s.last_error else ''}")
        return ("warning", probe_strategy if probe_strategy != "unknown" else "auto",
                f"最近抓取完成但暂无新内容。{probe_message}".strip())
    if probe_status != "unknown":
        return (probe_status, probe_strategy, probe_message)
    return ("unknown", "unknown", "")


def serialize_source(s: Source) -> dict:
    meta = s.metadata_ if isinstance(s.metadata_, dict) else {}
    probe = meta.get("probe", {})
    eff_status, eff_strategy, eff_message = _compute_fetch_status(s, probe)
    return {
        "id": str(s.id),
        "name": s.name,
        "type": s.type.value if hasattr(s.type, 'value') else s.type,
        "url": s.url,
        "extra_urls": _normalize_extra_urls(meta.get("extra_urls")),
        "category_id": str(s.category_id) if s.category_id else None,
        "fetch_interval": s.fetch_interval,
        "enabled": s.enabled,
        "priority": s.priority,
        "auth_required": s.auth_required,
        "auth_config_id": str(s.auth_config_id) if s.auth_config_id else None,
        "last_fetched_at": to_iso_z(s.last_fetched_at),
        "last_content_id": s.last_content_id,
        "last_error": s.last_error,
        "error_count": s.error_count,
        "metadata": meta,
        "fetch_status": eff_status,
        "fetch_strategy": eff_strategy,
        "fetch_status_message": eff_message,
        "probed_at": probe.get("probed_at"),
        "created_at": to_iso_z(s.created_at),
        "updated_at": to_iso_z(s.updated_at),
    }
