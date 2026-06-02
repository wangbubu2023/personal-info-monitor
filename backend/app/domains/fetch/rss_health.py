"""RSS feed health + discovery-cache helpers.

For an info-monitor, RSS is the highest-leverage path (structured, cheap,
low anti-bot pressure — plan §9). These helpers let the system treat a feed as
a first-class, diagnosable resource:

* :func:`assess_feed_health` — turn parse status / item count / last-update into
  a :class:`FeedHealth` verdict so "feed is stale" is distinguished from
  "source failed".
* :func:`persist_discovered_feed` — cache an auto-discovered feed URL back into
  ``Source.metadata_`` so we don't re-probe common paths every cycle.
* :func:`dedupe_feed_entries` — collapse the union of multiple feeds (per-section
  feeds for one source) down to one row per article.

All pure / metadata-only; no new tables.
"""

from __future__ import annotations

from calendar import timegm
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

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

    def to_metadata(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "healthy": self.healthy,
            "item_count": self.item_count,
            "last_update": (self.last_update.isoformat() + "Z") if self.last_update else None,
            "stale_days": self.stale_days,
            "reason": self.reason,
            "checked_at": utcnow_naive().isoformat() + "Z",
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


def record_feed_health(source, health: FeedHealth, *, feed_url: str | None = None) -> None:
    """Persist the latest feed-health verdict under ``metadata['rss_health']``."""
    metadata = dict(source.metadata_ or {})
    payload = health.to_metadata()
    if feed_url:
        payload["feed_url"] = feed_url
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


def dedupe_feed_entries(entries: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Collapse entries from one or more feeds to one row per article.

    Keyed on ``external_id`` then ``url``; the first occurrence wins so feed
    ordering (usually newest-first) is preserved.
    """
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for entry in entries:
        key = str(entry.get("external_id") or entry.get("url") or "").strip()
        if not key:
            out.append(dict(entry))
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(entry))
    return out


__all__ = [
    "FeedHealth",
    "extract_feed_signals",
    "assess_feed_health",
    "assess_parsed_feed_health",
    "record_feed_health",
    "persist_discovered_feed",
    "dedupe_feed_entries",
]
