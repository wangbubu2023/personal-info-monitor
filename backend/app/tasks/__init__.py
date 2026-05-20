"""Background tasks package (APScheduler + asyncio).

Phase 7 retired the legacy re-export bundle. Importers must address the
canonical submodule (e.g. ``app.tasks.fetch_tasks``, ``app.tasks.email_tasks``,
``app.domains.ingest.finish``) rather than dotting into this package alias.
"""
