"""LLM summarisation/translation, reader, digest, notifications.

Phase 4 of the refactor moves all LLM-bound and user-facing post-processing
into this package:

* ``domains/enrich/content/`` — summariser, translator, manual reprocess
* ``domains/enrich/reader/`` — moved from ``app/services/reader/``
  (Reader body loader, NDJSON streaming, translation orchestration)
* ``domains/enrich/digest/`` — daily digest service
* ``domains/enrich/hourly/`` — 3-hourly digest (the ``hourly_digest_tasks``
  name is kept on the HTTP boundary for backwards compatibility)
* ``domains/enrich/ranking.py`` — event clustering / scoring
* ``domains/enrich/notifications.py`` — keyword/doctor alert content
  (SMTP transport lives in ``platform.notifications``)

The enrich domain consumes atoms exclusively through
:class:`app.domains.contracts.atoms.AtomReader` — it never imports the
atoms implementation directly.

Phase progress:

* ``domains/enrich/reader/shared.py`` — moved from
  ``app.api.content_shared`` in Phase 4 step 1 (paragraph split, X-body
  clean, title heuristics, translation-validity gates, X article URL
  extraction, reader-body hash, clean reader HTML builder). The reader
  service modules (``services/reader/{body_loader, streaming,
  translation}``) now import from this canonical location instead of
  reverse-depending on ``app.api``; the legacy
  ``app.api.content_shared`` path keeps the same symbols as re-exports
  through Phase 7.
* ``domains/enrich/content/reprocess.py`` — extracted from
  ``ContentProcessor.reprocess_content`` in Phase 4 step 4 (manual
  UI-triggered summary regeneration / re-translation of an existing
  Content row). The legacy method on ``ContentProcessor`` is now a
  thin wrapper that delegates here; ``tasks/process_tasks.process_content``
  keeps calling ``ContentProcessor().reprocess_content(...)`` unchanged.
"""
