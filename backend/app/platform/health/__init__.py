"""Platform-level health and liveness primitives.

Phase 5 step 12 of the refactor pulls the ``/livez`` (public liveness probe)
and ``/health`` (operator-only detailed health) endpoints out of
``app.main`` and into a dedicated platform module. ``app.main`` now simply
mounts :data:`health_router`; the per-check probe implementations live next
to one another in :mod:`app.platform.health.router` so they can be
reused/tested as a unit and so ``main.py`` stops carrying inline
business logic for things that belong to the platform layer.

The router exposes two endpoints:

* ``GET /livez`` — always-public liveness probe. Returns ``{"status": "ok"}``
  with HTTP 200 as long as the process is running. Used by the desktop
  shell bootstrap and the LaunchAgent watchdog.
* ``GET /health`` — operator-authenticated detailed probe that runs
  database, scheduler and disk-space checks and returns ``200`` (healthy)
  or ``503`` (degraded) accordingly.

Future siblings of :mod:`app.platform.health.router` may add structured
readiness checks (e.g. ``/readyz``) or per-subsystem ping endpoints; keep
that surface inside this package so the main app stays thin.
"""

from app.platform.health.router import health_router

__all__ = ["health_router"]
