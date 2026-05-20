"""Platform layer — cross-cutting infrastructure capabilities.

The platform layer hosts the **non-business** concerns that every domain
needs: configuration, auth, persistence, workers/queues, observability,
security, the browser pool, LLM providers, notifications transport,
export pipelines, health probes and runtime locks.

Rules (enforced from refactor Phase 5 onwards by
``backend/scripts/check_domain_imports.py``):

* ``platform.* MUST NOT import from app.domains.*``
* ``platform.* MAY import from app.models`` (shared ORM layer)
* Higher layers (``app.domains.*``, ``app.tasks.*``, ``app.interfaces.*``)
  are free to import from ``app.platform.*``

Phase 2 step 1 created this package together with :mod:`app.platform.locks`
in order to break the ``background.py -> app.services.runtime_lock_service``
circular dependency described in 蓝图 §1.4 / §10. The legacy
``app.services.runtime_lock_service`` shim was retired by the post-
Phase-7 audit; runtime-lock callers must address :mod:`app.platform.locks`
directly.
"""
