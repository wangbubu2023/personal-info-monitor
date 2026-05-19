"""Domain-driven module root for the PIM backend.

This package will eventually own the five business domains described in
``docs/MODULE_BOUNDARIES.md`` and ``PIM 模块化重构实施蓝图 v3``:

* ``sources`` — Source CRUD, probe, scheduling, status
* ``fetch``   — Collectors, auth/cookies runtime, FetchBatch production
* ``ingest``  — Dedup, quality, keyword match, scoring, persistence
* ``enrich``  — LLM summarisation/translation, reader, digest, notifications
* ``atoms``   — Optional structured (event/entity/relation) layer

Phase 0 only creates the empty packages and the cross-domain ``contracts``
package; no business logic moves here yet. See
``backend/scripts/check_domain_imports.py`` for the boundary checker that
guards the migration.
"""
