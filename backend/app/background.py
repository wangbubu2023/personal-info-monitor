"""In-memory concurrency primitives replacing Redis locks and Celery queues.

Designed for single-process architecture with high-concurrency fetching.
"""

import asyncio
import time
from contextlib import asynccontextmanager
from typing import Optional

from app.platform.locks import runtime_lock_service
from app.utils.logger import get_logger

logger = get_logger(__name__)


class FetchLock:
    """Per-source lock preventing duplicate fetches of the same source."""

    def __init__(self):
        self._locks: dict[str, float] = {}  # source_id -> expiry timestamp

    def acquire(self, source_id: str, ttl: int = 300) -> bool:
        key = f"fetch:{source_id}"
        try:
            return runtime_lock_service.acquire(key, ttl)
        except Exception as exc:
            logger.warning("DB lock acquire failed, falling back to in-memory lock: %s", exc)

        now = time.monotonic()
        # Clean expired
        expiry = self._locks.get(source_id)
        if expiry and expiry > now:
            return False
        self._locks[source_id] = now + ttl
        return True

    def release(self, source_id: str) -> None:
        key = f"fetch:{source_id}"
        try:
            runtime_lock_service.release(key)
            return
        except Exception as exc:
            logger.warning("DB lock release failed, falling back to in-memory lock: %s", exc)
        self._locks.pop(source_id, None)

    def is_locked(self, source_id: str) -> bool:
        key = f"fetch:{source_id}"
        try:
            return runtime_lock_service.is_locked(key)
        except Exception as exc:
            logger.warning("DB lock check failed, falling back to in-memory lock: %s", exc)

        expiry = self._locks.get(source_id)
        if not expiry:
            return False
        if expiry <= time.monotonic():
            self._locks.pop(source_id, None)
            return False
        return True


class DomainRateLimiter:
    """Per-domain rate limiter. Different domains are fully parallel."""

    def __init__(self, cooldown: float = 3.0):
        self._timestamps: dict[str, float] = {}
        self._cooldown = cooldown

    def acquire(self, domain: str) -> bool:
        if not domain:
            return True

        key = f"domain:{domain}"
        try:
            return runtime_lock_service.acquire(key, int(max(1.0, self._cooldown)))
        except Exception as exc:
            logger.warning("DB rate-limit lock failed, falling back to in-memory limiter: %s", exc)

        now = time.monotonic()
        last = self._timestamps.get(domain, 0.0)
        if now - last < self._cooldown:
            return False
        self._timestamps[domain] = now
        return True


class TaskTracker:
    """Track running background tasks for observability."""

    def __init__(self):
        self._running_fetches: int = 0
        self._running_processes: int = 0
        self._lock = asyncio.Lock()

    async def start_fetch(self):
        async with self._lock:
            self._running_fetches += 1

    async def end_fetch(self):
        async with self._lock:
            self._running_fetches = max(0, self._running_fetches - 1)

    async def start_process(self):
        async with self._lock:
            self._running_processes += 1

    async def end_process(self):
        async with self._lock:
            self._running_processes = max(0, self._running_processes - 1)

    @asynccontextmanager
    async def track_fetch(self):
        """Context manager that auto-decrements fetch counter on exit."""
        await self.start_fetch()
        try:
            yield
        finally:
            await self.end_fetch()

    @asynccontextmanager
    async def track_process(self):
        """Context manager that auto-decrements process counter on exit."""
        await self.start_process()
        try:
            yield
        finally:
            await self.end_process()

    @property
    def running_fetches(self) -> int:
        return self._running_fetches

    @property
    def running_processes(self) -> int:
        return self._running_processes

    def status(self) -> dict:
        return {
            "running_fetches": self._running_fetches,
            "running_processes": self._running_processes,
        }


# Global singletons
fetch_lock = FetchLock()
domain_limiter = DomainRateLimiter()
task_tracker = TaskTracker()

# Concurrency controls
_fetch_semaphore: Optional[asyncio.Semaphore] = None
_llm_semaphore: Optional[asyncio.Semaphore] = None
_finalize_semaphore: Optional[asyncio.Semaphore] = None


def get_fetch_semaphore() -> asyncio.Semaphore:
    """Lazy init — must be called after event loop is running."""
    global _fetch_semaphore
    if _fetch_semaphore is None:
        from app.config import get_settings
        _fetch_semaphore = asyncio.Semaphore(get_settings().fetch_concurrency)
    return _fetch_semaphore


def get_llm_semaphore() -> asyncio.Semaphore:
    global _llm_semaphore
    if _llm_semaphore is None:
        _llm_semaphore = asyncio.Semaphore(2)
    return _llm_semaphore


def get_finalize_semaphore() -> asyncio.Semaphore:
    """Limit post-fetch finalization without consuming scarce LLM slots."""
    global _finalize_semaphore
    if _finalize_semaphore is None:
        from app.config import get_settings

        _finalize_semaphore = asyncio.Semaphore(max(1, min(get_settings().fetch_concurrency, 8)))
    return _finalize_semaphore
