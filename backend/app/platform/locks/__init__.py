"""Platform-level locking primitives.

Currently exposes the cross-process :class:`RuntimeLockService`
(database-backed advisory locks used by ``background.FetchLock`` and
``DomainRateLimiter``). Phase 2 step 1 moved the implementation out of
``app.services`` so the platform layer no longer has to lazy-import
from a business-services module.
"""

from app.platform.locks.runtime_lock import (  # noqa: F401 — re-export
    RuntimeLockService,
    runtime_lock_service,
)

__all__ = ["RuntimeLockService", "runtime_lock_service"]
