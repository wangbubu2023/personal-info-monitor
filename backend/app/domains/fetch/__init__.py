"""Collectors and the runtime that wraps them.

Phase 2 of the refactor populates:

* ``domains/fetch/collectors/`` — moved from ``app/collectors/`` (rss,
  website, x, youtube, podcast)
* ``domains/fetch/collector_stage.py`` — moved from ``app/pipeline``
* ``domains/fetch/auth/`` — split from ``app/tasks/fetch_auth_helpers.py``
  (480 lines, four-way fan-in)

The fetch domain emits :class:`app.domains.contracts.fetch.FetchBatch` and
:class:`app.domains.contracts.fetch.FetchOutcome` — it never writes to the
``Content`` table or invokes LLM providers.
"""
