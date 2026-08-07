"""Compatibility synchronization for the normalized source state tables."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models import (
    Source,
    SourceDiscoveryStats,
    SourceFetchState,
    SourcePolicy,
    SourceSessionState,
)
from app.utils.datetime import utcnow_naive


def _state_values(source: Source) -> dict[str, Any]:
    return {
        "fetch": {
            "last_fetched_at": source.last_fetched_at,
            "last_content_id": source.last_content_id,
            "last_error": source.last_error,
            "error_count": source.error_count or 0,
            "failure_code": source.fetch_failure_code,
            "failure_status": source.fetch_failure_status,
            "failure_severity": source.fetch_failure_severity,
            "cooldown_until": source.fetch_cooldown_until,
        },
        "discovery": {
            "checked_at": source.discovery_checked_at,
            "total": source.discovery_total,
            "kept": source.discovery_kept,
            "dropped": {
                "no_url": source.discovery_dropped_no_url,
                "off_domain": source.discovery_dropped_off_domain,
                "deny": source.discovery_dropped_deny,
                "allow_miss": source.discovery_dropped_allow_miss,
                "non_article_url": source.discovery_dropped_non_article_url,
                "short_title": source.discovery_dropped_short_title,
                "duplicate": source.discovery_dropped_duplicate,
                "stale": source.discovery_dropped_stale,
            },
            "pagination": {
                "truncated": source.discovery_truncated,
                "listing_urls_configured": source.discovery_listing_urls_configured,
                "pages_total": source.discovery_listing_pages_total,
                "pages_fetched": source.discovery_listing_pages_fetched,
                "pages_failed": source.discovery_listing_pages_failed,
                "max_pages": source.discovery_pagination_max_pages,
            },
        },
        "session": {
            "status": source.session_health_status,
            "reason": source.session_health_reason,
            "suggested_action": source.session_health_suggested_action,
            "validated_at": source.session_health_validated_at,
            "details": source.session_health_details or {},
            "alert_reason": source.session_health_alert_reason,
            "alert_sent_at": source.session_health_alert_sent_at,
        },
        "policy": {
            "enabled": bool(source.enabled),
            "fetch_interval": int(source.fetch_interval or 60),
            "use_keyword_filter": bool(source.use_keyword_filter),
            "auth_required": bool(source.auth_required),
            "metadata": source.metadata_ if isinstance(source.metadata_, dict) else {},
        },
    }


def ensure_source_state(db: Session, source: Source) -> None:
    values = _state_values(source)
    fetch = db.query(SourceFetchState).filter(SourceFetchState.source_id == source.id).first()
    if fetch is None:
        fetch = SourceFetchState(id=str(uuid.uuid4()), source_id=str(source.id))
        db.add(fetch)
    for key, value in values["fetch"].items():
        setattr(fetch, key, value)

    discovery = db.query(SourceDiscoveryStats).filter(SourceDiscoveryStats.source_id == source.id).first()
    if discovery is None:
        discovery = SourceDiscoveryStats(id=str(uuid.uuid4()), source_id=str(source.id))
        db.add(discovery)
    discovery.checked_at = values["discovery"]["checked_at"]
    discovery.total = values["discovery"]["total"]
    discovery.kept = values["discovery"]["kept"]
    discovery.dropped = values["discovery"]["dropped"]
    discovery.pagination = values["discovery"]["pagination"]

    session_state = db.query(SourceSessionState).filter(SourceSessionState.source_id == source.id).first()
    if session_state is None:
        session_state = SourceSessionState(id=str(uuid.uuid4()), source_id=str(source.id))
        db.add(session_state)
    for key, value in values["session"].items():
        setattr(session_state, key, value)

    policy = db.query(SourcePolicy).filter(SourcePolicy.source_id == source.id).first()
    if policy is None:
        policy = SourcePolicy(id=str(uuid.uuid4()), source_id=str(source.id))
        db.add(policy)
    policy.enabled = values["policy"]["enabled"]
    policy.fetch_interval = values["policy"]["fetch_interval"]
    policy.use_keyword_filter = values["policy"]["use_keyword_filter"]
    policy.auth_required = values["policy"]["auth_required"]
    policy.metadata_ = values["policy"]["metadata"]
    policy.updated_at = utcnow_naive()


def backfill_source_state(db: Session, *, limit: int = 500) -> int:  # noqa: V103
    sources = db.query(Source).order_by(Source.created_at.asc()).limit(max(1, int(limit))).all()
    for source in sources:
        ensure_source_state(db, source)
    if sources:
        db.commit()
    return len(sources)


async def ensure_source_state_async(db: AsyncSession, source: Source) -> None:
    """Async equivalent used by the HTTP source mutation transaction."""

    result = await db.execute(select(SourceFetchState).filter(SourceFetchState.source_id == source.id))
    if result.scalar_one_or_none() is None:
        # The sync helper is intentionally not used on AsyncSession; add all
        # rows directly so the write participates in the caller transaction.
        values = _state_values(source)
        db.add(SourceFetchState(id=str(uuid.uuid4()), source_id=str(source.id), **values["fetch"]))
        db.add(
            SourceDiscoveryStats(
                id=str(uuid.uuid4()),
                source_id=str(source.id),
                checked_at=values["discovery"]["checked_at"],
                total=values["discovery"]["total"],
                kept=values["discovery"]["kept"],
                dropped=values["discovery"]["dropped"],
                pagination=values["discovery"]["pagination"],
            )
        )
        db.add(SourceSessionState(id=str(uuid.uuid4()), source_id=str(source.id), **values["session"]))
        policy_values = dict(values["policy"])
        policy_values["metadata_"] = policy_values.pop("metadata")
        db.add(SourcePolicy(id=str(uuid.uuid4()), source_id=str(source.id), **policy_values))
        return
    # Existing rows are reconciled by the durable backfill/repair command.


def source_state_snapshot(db: Session, source_id: str) -> dict[str, Any]:  # noqa: V103
    fetch = db.query(SourceFetchState).filter(SourceFetchState.source_id == source_id).first()
    discovery = db.query(SourceDiscoveryStats).filter(SourceDiscoveryStats.source_id == source_id).first()
    session_state = db.query(SourceSessionState).filter(SourceSessionState.source_id == source_id).first()
    policy = db.query(SourcePolicy).filter(SourcePolicy.source_id == source_id).first()
    if not any((fetch, discovery, session_state, policy)):
        return {}
    return {
        "fetch": {"last_fetched_at": fetch.last_fetched_at.isoformat() if fetch and fetch.last_fetched_at else None, "last_content_id": fetch.last_content_id if fetch else None, "last_error": fetch.last_error if fetch else None, "error_count": fetch.error_count if fetch else 0, "failure_code": fetch.failure_code if fetch else None},
        "discovery": {"checked_at": discovery.checked_at.isoformat() if discovery and discovery.checked_at else None, "total": discovery.total if discovery else None, "kept": discovery.kept if discovery else None, "dropped": discovery.dropped if discovery else {}, "pagination": discovery.pagination if discovery else {}},
        "session": {"status": session_state.status if session_state else None, "reason": session_state.reason if session_state else None, "suggested_action": session_state.suggested_action if session_state else None, "details": session_state.details if session_state else {}},
        "policy": {"enabled": policy.enabled if policy else None, "fetch_interval": policy.fetch_interval if policy else None, "use_keyword_filter": policy.use_keyword_filter if policy else None, "auth_required": policy.auth_required if policy else None, "metadata": policy.metadata_ if policy else {}},
    }
