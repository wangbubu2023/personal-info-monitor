"""Tests for app.background — TaskTracker, FetchLock, DomainRateLimiter."""

import time
from unittest.mock import patch, MagicMock

import pytest

from app.background import TaskTracker, FetchLock, DomainRateLimiter


# ===========================================================================
# TaskTracker
# ===========================================================================

class TestTaskTracker:

    @pytest.mark.asyncio
    async def test_fetch_count_start_end(self):
        tracker = TaskTracker()
        assert tracker._running_fetches == 0
        await tracker.start_fetch()
        assert tracker._running_fetches == 1
        await tracker.end_fetch()
        assert tracker._running_fetches == 0

    @pytest.mark.asyncio
    async def test_process_count_start_end(self):
        tracker = TaskTracker()
        assert tracker._running_processes == 0
        await tracker.start_process()
        assert tracker._running_processes == 1
        await tracker.end_process()
        assert tracker._running_processes == 0

    @pytest.mark.asyncio
    async def test_context_manager_fetch(self):
        tracker = TaskTracker()
        async with tracker.track_fetch():
            assert tracker._running_fetches == 1
        assert tracker._running_fetches == 0

    @pytest.mark.asyncio
    async def test_context_manager_process(self):
        tracker = TaskTracker()
        async with tracker.track_process():
            assert tracker._running_processes == 1
        assert tracker._running_processes == 0

    @pytest.mark.asyncio
    async def test_context_manager_decrements_on_exception(self):
        tracker = TaskTracker()
        with pytest.raises(ValueError):
            async with tracker.track_fetch():
                assert tracker._running_fetches == 1
                raise ValueError("boom")
        assert tracker._running_fetches == 0

    @pytest.mark.asyncio
    async def test_process_context_manager_decrements_on_exception(self):
        tracker = TaskTracker()
        with pytest.raises(RuntimeError):
            async with tracker.track_process():
                assert tracker._running_processes == 1
                raise RuntimeError("fail")
        assert tracker._running_processes == 0

    @pytest.mark.asyncio
    async def test_end_fetch_never_negative(self):
        tracker = TaskTracker()
        await tracker.end_fetch()
        assert tracker._running_fetches == 0

    @pytest.mark.asyncio
    async def test_end_process_never_negative(self):
        tracker = TaskTracker()
        await tracker.end_process()
        assert tracker._running_processes == 0

    @pytest.mark.asyncio
    async def test_running_fetches_property(self):
        tracker = TaskTracker()
        await tracker.start_fetch()
        assert tracker.running_fetches == 1
        await tracker.end_fetch()
        assert tracker.running_fetches == 0

    @pytest.mark.asyncio
    async def test_running_processes_property(self):
        tracker = TaskTracker()
        await tracker.start_process()
        assert tracker.running_processes == 1
        await tracker.end_process()
        assert tracker.running_processes == 0

    @pytest.mark.asyncio
    async def test_status_dict(self):
        tracker = TaskTracker()
        await tracker.start_fetch()
        await tracker.start_process()
        status = tracker.status()
        assert status == {"running_fetches": 1, "running_processes": 1}

    @pytest.mark.asyncio
    async def test_multiple_concurrent_fetches(self):
        tracker = TaskTracker()
        await tracker.start_fetch()
        await tracker.start_fetch()
        await tracker.start_fetch()
        assert tracker._running_fetches == 3
        await tracker.end_fetch()
        assert tracker._running_fetches == 2


# ===========================================================================
# FetchLock
# ===========================================================================

class TestFetchLock:

    def test_acquire_and_release(self):
        lock = FetchLock()
        with patch("app.background.runtime_lock_service") as mock_svc:
            mock_svc.acquire.return_value = True
            assert lock.acquire("src-1") is True
            mock_svc.acquire.assert_called_once()

            mock_svc.release.return_value = None
            lock.release("src-1")
            mock_svc.release.assert_called_once()

    def test_acquire_fallback_on_db_error(self):
        lock = FetchLock()
        with patch("app.background.runtime_lock_service") as mock_svc:
            mock_svc.acquire.side_effect = RuntimeError("db down")
            assert lock.acquire("src-1", ttl=5) is True

    def test_acquire_blocked_by_unexpired_lock(self):
        lock = FetchLock()
        with patch("app.background.runtime_lock_service") as mock_svc:
            mock_svc.acquire.side_effect = RuntimeError("db down")
            lock.acquire("src-1", ttl=300)
            assert lock.acquire("src-1", ttl=300) is False

    def test_is_locked_true(self):
        lock = FetchLock()
        with patch("app.background.runtime_lock_service") as mock_svc:
            mock_svc.is_locked.return_value = True
            assert lock.is_locked("src-1") is True

    def test_is_locked_fallback_expired(self):
        lock = FetchLock()
        with patch("app.background.runtime_lock_service") as mock_svc:
            mock_svc.is_locked.side_effect = RuntimeError("db down")
            assert lock.is_locked("src-1") is False

    def test_release_fallback_on_db_error(self):
        lock = FetchLock()
        lock._locks["src-1"] = time.monotonic() + 300
        with patch("app.background.runtime_lock_service") as mock_svc:
            mock_svc.release.side_effect = RuntimeError("db down")
            lock.release("src-1")
        assert "src-1" not in lock._locks


# ===========================================================================
# DomainRateLimiter
# ===========================================================================

class TestDomainRateLimiter:

    def test_acquire_empty_domain_always_true(self):
        limiter = DomainRateLimiter()
        with patch("app.background.runtime_lock_service") as mock_svc:
            assert limiter.acquire("") is True

    def test_acquire_delegates_to_service(self):
        limiter = DomainRateLimiter(cooldown=5.0)
        with patch("app.background.runtime_lock_service") as mock_svc:
            mock_svc.acquire.return_value = True
            assert limiter.acquire("example.com") is True

    def test_acquire_fallback_on_error(self):
        limiter = DomainRateLimiter(cooldown=0.0)
        with patch("app.background.runtime_lock_service") as mock_svc:
            mock_svc.acquire.side_effect = RuntimeError("db down")
            assert limiter.acquire("example.com") is True

    def test_cooldown_blocks_second_acquire(self):
        limiter = DomainRateLimiter(cooldown=60.0)
        with patch("app.background.runtime_lock_service") as mock_svc:
            mock_svc.acquire.side_effect = RuntimeError("db down")
            limiter.acquire("example.com")
            assert limiter.acquire("example.com") is False
