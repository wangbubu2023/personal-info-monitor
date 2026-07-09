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
from app.platform.config.system_settings import get_system_settings_async
from app.utils.datetime import to_iso_z
from app.utils.ttl_cache import TTLCache
from app.utils.url import host_matches, normalize_host, normalize_source_url_for_dedupe
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
    # Tests monkeypatch app.api.sources.get_system_settings_async or
    # app.api.sources._helpers.get_system_settings_async to inject quotas;
    # both forms resolve to the imported symbol here, so we keep the direct
    # reference and rely on standard from-import semantics.
    settings = await get_system_settings_async(db)
    limits = settings.get("limits") if isinstance(settings, dict) else {}
    limits = limits if isinstance(limits, dict) else {}
    return _coerce_limit_int(limits.get("max_sources"), 200, min_value=1, max_value=5000)


async def find_duplicate_source_by_normalized_url(
    db: AsyncSession,
    url: str,
    source_type: object,
    *,
    exclude_source_id: Optional[UUID] = None,
) -> Optional[Source]:
    """Return an existing source with the same type and normalized URL, if any."""
    target = normalize_source_url_for_dedupe(url)
    if not target:
        return None
    try:
        st = SourceType(_source_type_value(source_type))
    except ValueError:
        return None
    q = select(Source).filter(Source.type == st)
    if exclude_source_id is not None:
        q = q.filter(Source.id != str(exclude_source_id))
    result = await db.execute(q)
    for row in result.scalars().all():
        if normalize_source_url_for_dedupe(row.url) == target:
            return row
    return None


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


async def _find_shared_x_cookie_auth_config_id(db: AsyncSession) -> Optional[UUID]:
    """Return the newest shared X cookie auth config, if any."""
    from app.interfaces.http.configs_common_auth import is_shared_x_cookie_config

    result = await db.execute(select(AuthConfig).order_by(AuthConfig.updated_at.desc()))
    for cfg in result.scalars().all():
        if is_shared_x_cookie_config(cfg):
            return cfg.id
    return None


async def resolve_x_source_auth(
    db: AsyncSession,
    *,
    source_type: object,
    auth_config_id: Optional[UUID],
    auth_required: bool,
) -> tuple[bool, Optional[UUID]]:
    """Auto-bind shared X cookie auth for new X sources without explicit auth."""
    if _source_type_value(source_type) != "x":
        return auth_required, auth_config_id
    if auth_config_id:
        return auth_required, auth_config_id
    matched = await _find_shared_x_cookie_auth_config_id(db)
    if matched:
        return True, matched
    return auth_required, auth_config_id


async def _load_source_probe_cookies(
    db: AsyncSession, source: Source
) -> Dict[str, str]:
    """Resolve cookies attached to ``source.auth_config`` for probe reuse.

    Paywalled sites (WSJ, NYT, …) only return the public shell when probed
    anonymously. When the user has configured an auth_config with cookies,
    reuse them so the probe reflects the same access the fetch pipeline has.
    Returns an empty dict on any failure — probes must stay best-effort.
    """
    normalized: Dict[str, str] = {}
    if not getattr(source, "auth_config_id", None):
        return _merge_x_metadata_probe_cookies(source, normalized)
    try:
        result = await db.execute(
            select(AuthConfig).filter(AuthConfig.id == source.auth_config_id)
        )
        auth_config = result.scalar_one_or_none()
    except Exception as exc:  # noqa: BLE001 - DB issues shouldn't block probing
        logger.debug("Probe cookie load failed for source %s: %s", source.id, exc)
        return _merge_x_metadata_probe_cookies(source, normalized)
    if auth_config is None:
        return _merge_x_metadata_probe_cookies(source, normalized)

    from app.domains.fetch.auth import try_parse_auth_credentials

    creds = try_parse_auth_credentials(auth_config)
    cookies = creds.get("cookies") if isinstance(creds, dict) else None
    if not isinstance(cookies, dict):
        return _merge_x_metadata_probe_cookies(source, normalized)
    for name, value in cookies.items():
        key = str(name or "").strip()
        if not key or value is None:
            continue
        normalized[key] = str(value)
    return _merge_x_metadata_probe_cookies(source, normalized)


def _merge_x_metadata_probe_cookies(source: Source, cookies: Dict[str, str]) -> Dict[str, str]:
    """Map legacy source metadata X tokens into probe cookies when present."""
    source_type = _source_type_value(getattr(source, "type", None))
    if source_type != "x":
        return cookies
    metadata = source.metadata_ if isinstance(source.metadata_, dict) else {}
    auth_token = metadata.get("x_auth_token") or metadata.get("auth_token")
    ct0 = metadata.get("x_ct0_token") or metadata.get("ct0")
    if auth_token and ct0:
        cookies.setdefault("auth_token", str(auth_token))
        cookies.setdefault("ct0", str(ct0))
    return cookies


def _pending_probe_metadata() -> dict:
    return {
        "status": "pending",
        "strategy": "unknown",
        "rss_url": None,
        "message": "正在后台探测可用性…",
        "sample_count": 0,
        "probed_at": None,
    }


def _failed_probe_metadata(exc: Exception) -> dict:
    return {
        "status": "failed",
        "strategy": "unknown",
        "rss_url": None,
        "message": str(exc)[:200],
        "sample_count": 0,
        "probed_at": None,
    }


def _merge_probe_into_metadata(
    metadata: dict,
    probe_result,
    rss_urls: Dict[str, str],
    primary_url: str,
    source_type: str,
) -> None:
    metadata["probe"] = probe_result.to_dict()
    if source_type == "x" and probe_result.strategy in {"rsshub", "nitter", "api"}:
        metadata["strategy"] = probe_result.strategy
    if rss_urls:
        metadata["rss_urls"] = rss_urls
    if primary_url in rss_urls:
        metadata["rss_url"] = rss_urls[primary_url]
    elif probe_result.rss_url and "rss_url" not in metadata:
        metadata["rss_url"] = probe_result.rss_url


async def _background_probe_source(
    source_id: UUID,
    urls: List[str],
    source_type: str,
    primary_url: str,
) -> None:
    """Update probe metadata after create — must not block the HTTP response."""
    from app.database import AsyncSessionLocal

    cookies: Dict[str, str] = {}
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Source).filter(Source.id == source_id))
            source = result.scalar_one_or_none()
            if not source or not _source_is_visible(source):
                return
            cookies = await _load_source_probe_cookies(db, source)

        probe_result, rss_urls, _ = await _probe_urls(urls, source_type, cookies=cookies)

        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Source).filter(Source.id == source_id))
            source = result.scalar_one_or_none()
            if not source:
                return
            meta = dict(source.metadata_ or {})
            _merge_probe_into_metadata(meta, probe_result, rss_urls, primary_url, source_type)
            source.metadata_ = meta
            await db.commit()
        _invalidate_source_cache()
    except Exception as exc:
        logger.warning("Background probe failed for source %s: %s", source_id, exc)
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(Source).filter(Source.id == source_id))
                source = result.scalar_one_or_none()
                if not source:
                    return
                meta = dict(source.metadata_ or {})
                meta["probe"] = _failed_probe_metadata(exc)
                source.metadata_ = meta
                await db.commit()
            _invalidate_source_cache()
        except Exception:
            logger.exception("Failed to persist probe failure for source %s", source_id)


async def schedule_post_create_probe(
    source_id: UUID,
    urls: List[str],
    source_type: str,
    primary_url: str,
) -> None:
    import asyncio

    asyncio.create_task(_background_probe_source(source_id, urls, source_type, primary_url))


async def _probe_urls(
    urls: List[str],
    source_type: str,
    *,
    cookies: Optional[Dict[str, str]] = None,
):
    import asyncio
    from app.domains.sources.probe.service import ProbeService
    _probe_service = ProbeService()
    tasks = [_probe_service.probe(url, source_type, cookies=cookies) for url in urls]
    probe_results = await asyncio.gather(*tasks, return_exceptions=True)
    paired = [(url, r) for url, r in zip(urls, probe_results) if not isinstance(r, Exception)]
    if not paired:
        fallback = await _probe_service.probe(urls[0], source_type, cookies=cookies)
        return fallback, {}, 0
    return _pick_best_probe(paired)


def _compute_fetch_status(s: Source) -> tuple[str, str, str]:
    """Reflect real fetch history only — not URL probe results."""
    from app.domains.sources.status import last_fetch_outcome_metadata

    metadata = s.metadata_ if isinstance(s.metadata_, dict) else {}
    configured_strategy = str(metadata.get("strategy") or metadata.get("probe", {}).get("strategy") or "unknown")
    outcome = last_fetch_outcome_metadata(s)
    outcome_severity = str(outcome.get("severity") or "").strip().lower()
    outcome_message = str(outcome.get("message") or "").strip()
    has_content = bool(s.last_content_id)
    has_fetched = s.last_fetched_at is not None
    has_errors = s.error_count > 0 and s.last_error
    strategy = configured_strategy if configured_strategy != "unknown" else "auto"

    if has_fetched and outcome_severity == "error":
        return ("error", strategy, outcome_message or "最近抓取失败")
    if has_fetched and outcome_severity == "warning":
        return ("warning", strategy, outcome_message or "最近抓取部分受限")
    if has_content and has_fetched:
        if has_errors:
            return (
                "warning",
                strategy,
                f"已成功抓取过内容，但最近有错误: {s.last_error[:60] if s.last_error else ''}",
            )
        return ("ok", strategy, "已成功抓取内容")
    if has_fetched and not has_content:
        if has_errors:
            return ("error", strategy, f"抓取失败: {s.last_error[:60] if s.last_error else ''}")
        return ("warning", strategy, "最近抓取完成但暂无新内容")
    return ("unknown", "unknown", "尚未抓取")


def _compute_probe_display(probe: dict) -> tuple[str, str, str]:
    """Reflect last explicit probe only — independent of fetch history."""
    if not probe:
        return ("not_probed", "unknown", "尚未探测，可点击「探测」检查可抓取性")
    status = str(probe.get("status") or "unknown")
    strategy = str(probe.get("strategy") or "unknown")
    message = str(probe.get("message") or "").strip()
    if status == "pending":
        return ("pending", strategy, message or "探测中…")
    if not message:
        message = {
            "ok": "探测通过",
            "warning": "探测有告警",
            "error": "探测失败",
            "failed": "探测失败",
        }.get(status, "尚未探测")
    return (status, strategy, message)


def _fetch_health_fields(s: Source, meta: dict) -> dict:
    """Surface the structured fetch-failure code + rolling profile for the UI.

    Reads structured ``sources.fetch_failure_*`` columns first, with the legacy
    metadata blob as fallback; degrades silently to an empty dict so a missing
    or malformed blob never breaks source listing.
    """
    fields: dict = {}
    try:
        from app.domains.fetch.profile import summarize_profile

        failure = meta.get("fetch_failure") if isinstance(meta.get("fetch_failure"), dict) else {}
        cooldown_until = getattr(s, "fetch_cooldown_until", None)
        fields["last_failure_code"] = getattr(s, "fetch_failure_code", None) or failure.get("last_code")
        fields["cooldown_until"] = (
            cooldown_until.isoformat() + "Z"
            if cooldown_until is not None
            else failure.get("cooldown_until")
        )
        fields["fetch_profile_summary"] = summarize_profile(s)
    except Exception as exc:  # noqa: BLE001 — serialization must stay resilient
        logger.debug("Fetch health serialization failed for %s: %s", getattr(s, "id", "?"), exc)
    return fields


def serialize_source(s: Source, *, content_count: int | None = None) -> dict:
    meta = s.metadata_ if isinstance(s.metadata_, dict) else {}
    try:
        from app.domains.fetch.rss_health import feed_health_metadata

        rss_health = feed_health_metadata(s)
        if rss_health:
            meta = dict(meta)
            meta["rss_health"] = rss_health
    except (AttributeError, TypeError, ValueError) as exc:
        logger.debug("RSS health serialization failed for %s: %s", getattr(s, "id", "?"), exc)
    try:
        from app.domains.fetch.discovery import discovery_diagnostics_metadata

        discovery_diagnostics = discovery_diagnostics_metadata(s)
        if discovery_diagnostics:
            meta = dict(meta)
            meta["discovery_diagnostics"] = discovery_diagnostics
    except (AttributeError, TypeError, ValueError) as exc:
        logger.debug("Discovery diagnostics serialization failed for %s: %s", getattr(s, "id", "?"), exc)
    try:
        from app.domains.sources.status import last_fetch_outcome_metadata

        fetch_outcome = last_fetch_outcome_metadata(s)
        if fetch_outcome:
            meta = dict(meta)
            meta["last_fetch_outcome"] = fetch_outcome
    except (AttributeError, TypeError, ValueError) as exc:
        logger.debug("Fetch outcome serialization failed for %s: %s", getattr(s, "id", "?"), exc)
    try:
        from app.domains.fetch.session_health import session_health_alert_metadata, session_health_metadata

        session_health = session_health_metadata(s)
        session_alert = session_health_alert_metadata(s)
        if session_health or session_alert:
            meta = dict(meta)
        if session_health:
            meta["session_health"] = session_health
        if session_alert:
            meta["session_health_alert"] = session_alert
    except (AttributeError, TypeError, ValueError) as exc:
        logger.debug("Session health serialization failed for %s: %s", getattr(s, "id", "?"), exc)
    probe = meta.get("probe", {}) if isinstance(meta.get("probe"), dict) else {}
    fetch_status, fetch_strategy, fetch_message = _compute_fetch_status(s)
    probe_status, probe_strategy, probe_message = _compute_probe_display(probe)
    return {
        "id": str(s.id),
        "name": s.name,
        "type": s.type.value if hasattr(s.type, 'value') else s.type,
        "url": s.url,
        "extra_urls": _normalize_extra_urls(meta.get("extra_urls")),
        "fetch_interval": s.fetch_interval,
        "enabled": s.enabled,
        "auth_required": s.auth_required,
        "auth_config_id": str(s.auth_config_id) if s.auth_config_id else None,
        "last_fetched_at": to_iso_z(s.last_fetched_at),
        "last_content_id": s.last_content_id,
        "last_error": s.last_error,
        "error_count": s.error_count,
        "content_count": int(content_count or 0),
        "metadata": meta,
        "session_health": meta.get("session_health") if isinstance(meta.get("session_health"), dict) else None,
        "fetch_status": fetch_status,
        "fetch_strategy": fetch_strategy,
        "fetch_status_message": fetch_message,
        "probe_status": probe_status,
        "probe_strategy": probe_strategy,
        "probe_message": probe_message,
        "probed_at": probe.get("probed_at"),
        **_fetch_health_fields(s, meta),
        "created_at": to_iso_z(s.created_at),
        "updated_at": to_iso_z(s.updated_at),
    }
