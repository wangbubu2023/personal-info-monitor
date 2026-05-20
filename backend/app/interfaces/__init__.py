"""Interfaces — outward-facing adapters (HTTP, CLI, etc.).

Phase 5 step 15 of the refactor introduces the ``interfaces`` package as
the layered home for everything that translates external requests into
domain calls. The first sub-package is :mod:`app.interfaces.http`, which
holds the FastAPI routers previously living under ``app.api``.

The legacy ``app.api`` namespace is preserved as a thin re-export shim
(see ``app/api/__init__.py``); existing callers and test patch targets
continue to work unchanged until Phase 7 migrates them to the canonical
``app.interfaces.http.*`` paths.

Future siblings of :mod:`app.interfaces.http` may include:

* ``interfaces.cli`` — the ``pim``/``pimctl`` operator CLIs.
* ``interfaces.cron`` — operator-facing scheduled-job entry points
  (currently inside ``app.scheduler``).
"""
