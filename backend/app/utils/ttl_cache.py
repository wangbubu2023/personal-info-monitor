"""Small in-process TTL cache for hot read endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import Any, Dict


@dataclass
class _CacheEntry:
    value: Any
    expires_at: float


class TTLCache:
    """Simple lock-protected TTL cache."""

    def __init__(self, ttl_seconds: int) -> None:
        self.ttl_seconds = max(1, int(ttl_seconds))
        self._entries: Dict[str, _CacheEntry] = {}
        self._lock = Lock()

    def get(self, key: str) -> Any | None:
        now = monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if not entry:
                return None
            if entry.expires_at <= now:
                self._entries.pop(key, None)
                return None
            return entry.value

    def set(self, key: str, value: Any) -> Any:
        with self._lock:
            self._entries[key] = _CacheEntry(
                value=value,
                expires_at=monotonic() + self.ttl_seconds,
            )
        return value

    def invalidate(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._entries.clear()
                return
            self._entries.pop(key, None)
