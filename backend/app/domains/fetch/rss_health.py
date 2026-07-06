"""RSS feed health + discovery-cache helpers.

For an info-monitor, RSS is the highest-leverage path (structured, cheap,
low anti-bot pressure — plan §9). These helpers let the system treat a feed as
a first-class, diagnosable resource:

* :func:`assess_feed_health` — turn parse status / item count / last-update into
  a :class:`FeedHealth` verdict so "feed is stale" is distinguished from
  "source failed".
* :func:`persist_discovered_feed` — cache an auto-discovered feed URL back into
  ``Source.metadata_`` so we don't re-probe common paths every cycle.

The latest feed-health verdict is persisted to structured ``sources.rss_health_*``
columns first, while still mirrored to ``Source.metadata_['rss_health']`` for
older callers and the current frontend metadata contract.
"""

from __future__ import annotations

from calendar import timegm
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from app.utils.datetime import utcnow_naive

_STALE_AFTER_DAYS = 30

FeedStatus = str  # "ok" | "stale" | "empty" | "parse_error"


@dataclass(frozen=True)
class FeedHealth:
    status: FeedStatus
    healthy: bool
    item_count: int
    last_update: datetime | None
    stale_days: int | None
    reason: str

    def to_metadata(self, *, checked_at: datetime | None = None) -> dict[str, Any]:
        checked_at = checked_at or utcnow_naive()
        return {
            "status": self.status,
            "healthy": self.healthy,
            "item_count": self.item_count,
            "last_update": (self.last_update.isoformat() + "Z") if self.last_update else None,
            "stale_days": self.stale_days,
            "reason": self.reason,
            "checked_at": checked_at.isoformat() + "Z",
        }


def _entry_published(entry: Any) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        struct = getattr(entry, attr, None) if not isinstance(entry, Mapping) else entry.get(attr)
        if struct:
            try:
                return datetime.fromtimestamp(timegm(struct), tz=timezone.utc).replace(tzinfo=None)
            except (TypeError, ValueError, OverflowError):
                continue
    return None


def extract_feed_signals(parsed: Any) -> tuple[bool, int, datetime | None]:
    """Pull ``(parse_ok, item_count, latest_published)`` from a feedparser result."""
    entries = list(getattr(parsed, "entries", None) or [])
    bozo = bool(getattr(parsed, "bozo", False))
    parse_ok = (not bozo) or bool(entries)
    latest: datetime | None = None
    for entry in entries:
        published = _entry_published(entry)
        if published and (latest is None or published > latest):
            latest = published
    return parse_ok, len(entries), latest


def assess_feed_health(
    *,
    parse_ok: bool,
    item_count: int,
    latest_published: datetime | None,
    now: datetime | None = None,
    stale_after_days: int = _STALE_AFTER_DAYS,
) -> FeedHealth:
    """Classify a feed's health. A stale feed is *not* a hard failure (plan §9.4)."""
    now = now or utcnow_naive()
    if not parse_ok:
        return FeedHealth("parse_error", False, item_count, latest_published, None, "feed_parse_failed")
    if item_count <= 0:
        return FeedHealth("empty", False, 0, None, None, "no_entries")

    if latest_published is not None:
        stale_days = max(0, (now - latest_published).days)
        if stale_days > stale_after_days:
            return FeedHealth("stale", True, item_count, latest_published, stale_days, "no_recent_items")
        return FeedHealth("ok", True, item_count, latest_published, stale_days, "fresh")

    # No dated entries but items exist — usable, just can't judge freshness.
    return FeedHealth("ok", True, item_count, None, None, "fresh_unknown_dates")


def assess_parsed_feed_health(parsed: Any, *, now: datetime | None = None) -> FeedHealth:
    """Convenience: signals + health from a raw feedparser result in one call."""
    parse_ok, item_count, latest = extract_feed_signals(parsed)
    return assess_feed_health(parse_ok=parse_ok, item_count=item_count, latest_published=latest, now=now)


def _structured_feed_health_metadata(source) -> dict[str, Any]:
    status = getattr(source, "rss_health_status", None)
    if not status:
        return {}
    last_update = getattr(source, "rss_health_last_update", None)
    checked_at = getattr(source, "rss_health_checked_at", None)
    return {
        "status": status,
        "healthy": getattr(source, "rss_health_healthy", None),
        "item_count": getattr(source, "rss_health_item_count", None),
        "last_update": (last_update.isoformat() + "Z") if isinstance(last_update, datetime) else None,
        "stale_days": getattr(source, "rss_health_stale_days", None),
        "reason": getattr(source, "rss_health_reason", None),
        "checked_at": (checked_at.isoformat() + "Z") if isinstance(checked_at, datetime) else None,
        "feed_url": getattr(source, "rss_health_feed_url", None),
    }


def feed_health_metadata(source) -> dict[str, Any]:
    """Return latest feed health, preferring structured columns over metadata."""
    structured = _structured_feed_health_metadata(source)
    if structured:
        return structured
    metadata = getattr(source, "metadata_", None)
    if not isinstance(metadata, Mapping):
        return {}
    value = metadata.get("rss_health")
    return dict(value) if isinstance(value, Mapping) else {}


def _write_structured_feed_health(source, health: FeedHealth, *, feed_url: str | None, checked_at: datetime) -> None:
    if not hasattr(source, "rss_health_status"):
        return
    source.rss_health_status = health.status
    source.rss_health_healthy = health.healthy
    source.rss_health_item_count = health.item_count
    source.rss_health_last_update = health.last_update
    source.rss_health_stale_days = health.stale_days
    source.rss_health_reason = health.reason
    source.rss_health_checked_at = checked_at
    source.rss_health_feed_url = feed_url


def record_feed_health(source, health: FeedHealth, *, feed_url: str | None = None) -> None:
    """Persist the latest feed-health verdict to columns and metadata."""
    metadata = dict(source.metadata_ or {})
    checked_at = utcnow_naive()
    payload = health.to_metadata(checked_at=checked_at)
    if feed_url:
        payload["feed_url"] = feed_url
    _write_structured_feed_health(source, health, feed_url=feed_url, checked_at=checked_at)
    metadata["rss_health"] = payload
    source.metadata_ = metadata


def persist_discovered_feed(source, feed_url: str) -> bool:
    """Cache an auto-discovered feed URL so it isn't re-probed every cycle.

    Returns ``True`` when the metadata was changed.
    """
    feed_url = (feed_url or "").strip()
    if not feed_url:
        return False
    metadata = dict(source.metadata_ or {})
    changed = False
    if metadata.get("rss_url") != feed_url:
        metadata["rss_url"] = feed_url
        changed = True
    existing = metadata.get("rss_urls")
    urls = list(existing) if isinstance(existing, list) else []
    if feed_url not in urls:
        urls.append(feed_url)
        metadata["rss_urls"] = urls
        changed = True
    if changed:
        source.metadata_ = metadata
    return changed


__all__ = [
    "FeedHealth",
    "extract_feed_signals",
    "assess_feed_health",
    "assess_parsed_feed_health",
    "feed_health_metadata",
    "record_feed_health",
    "persist_discovered_feed",
]
