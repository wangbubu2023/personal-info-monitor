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
* ``domains/enrich/reader/{body_loader, translation, streaming}.py`` —
  moved from ``app.services.reader.*`` in Phase 4 step 5 (Reader 整包
  平移). ``app.api.contents_reader`` switched to import these directly
  from the canonical location; the ``app.services.reader.*`` paths
  remain as re-export shims (test patches that target internals were
  migrated to ``app.domains.enrich.reader.*`` paths in
  ``tests/test_contents_reader.py``).
* ``domains/enrich/hourly/{tasks, repository, selection, synthesis,
  text_utils}.py`` — moved from ``app.services.hourly_digest.*`` +
  ``app.tasks.hourly_digest_tasks`` in Phase 4 step 6 (hourly digest
  整包平移). ``app.scheduler`` and ``app.tasks.__init__`` switched to
  import ``generate_previous_hour_digest`` / ``clear_hourly_digests``
  from the canonical location; both legacy paths remain as
  ``from new import *`` re-export shims. The HTTP-facing ``hourly``
  naming on ``app/api/digest.py`` is preserved per the "must keep"
  list. ``tests/test_hourly_digest_limits.py`` was migrated to import
  ``synthesis``/``tasks``/``text_utils`` from the canonical module so
  that ``monkeypatch`` against wrapper-internal ``Translator`` /
  ``get_system_settings_sync`` hits the actual call sites, and to
  reach the underscore-prefixed legacy aliases that ``import *`` does
  not carry through the shim.
"""
