"""Domain-driven module root for the PIM backend.

This package will eventually own the five business domains described in
``docs/MODULE_BOUNDARIES.md`` and ``PIM 模块化重构实施蓝图 v3``:

* ``sources`` — Source CRUD, probe, scheduling, status
* ``fetch``   — Collectors, auth/cookies runtime, failure/session/discovery helpers
* ``ingest``  — Dedup, quality, keyword match, scoring, persistence
* ``enrich``  — LLM summarisation/translation, reader, digest, notifications
* ``atoms``   — Optional structured (event/entity/relation) layer

See ``backend/scripts/check_domain_imports.py`` for the boundary checker that
guards the migration.
"""
