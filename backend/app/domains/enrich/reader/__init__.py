"""Reader sub-domain — body extraction, paragraph split, translation orchestration.

Module layout (post Phase 4 steps 1 + 5 of the module-refactor blueprint):

* :mod:`.shared` — paragraph split, X-body clean, title heuristics,
  translation-validity gates, X article URL extraction, reader-body
  hash, clean reader HTML builder. Moved from ``app.api.content_shared``
  in Phase 4 step 1.
* :mod:`.body_loader` — fetch / backfill / clean reader body, X article
  full-text upgrade, source cookie loading. Moved from
  ``app.services.reader.body_loader`` in Phase 4 step 5.
* :mod:`.translation` — translator orchestration (title + body),
  translation cache persistence. Moved from
  ``app.services.reader.translation`` in Phase 4 step 5.
* :mod:`.streaming` — NDJSON frame rendering for the reader translate
  stream endpoint. Moved from ``app.services.reader.streaming`` in
  Phase 4 step 5.

The HTTP layer at ``app.api.contents_reader`` is kept thin — it imports
these submodules directly. Both ``app.api.content_shared`` and
``app.services.reader.*`` remain as re-export shims through Phase 7.
"""
