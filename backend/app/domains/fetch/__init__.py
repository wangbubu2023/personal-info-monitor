"""fetch domain.

Public entry point:

* :func:`fetch_source_batch` — accepts a :class:`FetchRequest`, returns a
  :class:`FetchBatch`. Phase 2 has this delegate to the legacy
  ``app.pipeline.CollectorStage`` (see ``app.domains.fetch.orchestrator``);
  later phases invert the dependency so the orchestrator owns the real
  fetch / auth / dedupe path and CollectorStage shrinks to a re-export shim.

Already populated sub-packages:

* :mod:`app.domains.fetch.auth` — cookies / login / refresh, extracted
  from ``app.tasks.fetch_auth_helpers`` in Phase 2.3.

Scheduled migrations (one PR per collector, Phase 2.6–2.10):

* ``domains/fetch/collectors/`` — moved from ``app/collectors/`` (rss,
  website, youtube, podcast, x).
* ``domains/fetch/collector_stage`` — owns multi-URL fan-out + dedupe +
  filter_new_content currently in ``app.pipeline.collector_stage``.

The fetch domain emits :class:`FetchBatch` and never writes to the
``Content`` table or invokes LLM providers.
"""

from app.domains.fetch.orchestrator import fetch_source_batch

__all__ = ["fetch_source_batch"]
