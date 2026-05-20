"""Platform-level FastAPI runtime composition.

Phase 5 step 13 of the refactor pulls the FastAPI ``lifespan`` context
manager out of :mod:`app.main` and into this package. ``app.main`` is
still the composition root that picks the concrete domain handlers and
calls :func:`build_lifespan` to wire them in; the resulting context
manager performs every startup/shutdown side-effect (migrations,
scheduler bootstrap, task-queue workers, browser-pool disposal, metrics
checkpointing).

The ``build_lifespan(fetch_handler=..., process_handler=...)`` factory
keeps the platform layer strictly free of ``app.domains`` imports — the
handlers are supplied by ``app.main``, which is the only place allowed
to bridge domains and the FastAPI runtime.

Future siblings of :mod:`app.platform.runtime.lifespan` may include:

* ``platform.runtime.middleware`` — the request-ID / latency middleware
  currently inlined in :mod:`app.main`.
* ``platform.runtime.spa`` — the SPA + ``/local-token`` serving stack.
"""

from app.platform.runtime.lifespan import build_lifespan

__all__ = ["build_lifespan"]
