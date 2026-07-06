"""Dedup, quality, keyword match, scoring, persistence.

Phase 3 of the refactor consolidates the post-collection / pre-LLM logic
here:

* ``domains/ingest/quality.py`` — owns
  ``get_website_content_reject_reason`` (Phase 2 step 7 / Phase 3 step 1;
  legacy ``pipeline/utils.get_website_content_reject_reason`` is a
  re-export shim).
* ``domains/ingest/quality_metadata.py`` — owns ``ContentQuality``,
  ``assess_content_quality`` and ``merge_content_quality_metadata``
  (Phase 3 step 4; legacy
  ``app.services.content_quality_service`` is a re-export shim).
* ``domains/ingest/dedupe.py``, ``normalizer.py``, ``storage.py`` — moved
  from ``app/pipeline`` in Phase 3 step 2 (legacy ``app.pipeline.*`` paths
  remain as re-export shims so existing test ``patch`` targets keep
  resolving through Phase 7).
* ``domains/ingest/build_content.py`` — owns ``build_raw_content_objects``
  (the LLM-free portion of the raw → ORM Content build). The fetch
  coordinator imports this canonical helper directly; wrapper-internal
  helpers (``strip_html_tags`` etc.) live next to the implementation and
  must be patched at
  ``app.domains.ingest.build_content.<name>``.
* ``domains/ingest/extractor.py`` — moved from
  ``app.processors.extractor`` in Phase 3 step 4 (HTML → main-content
  text extraction; readability + trafilatura + BeautifulSoup
  fallbacks). The legacy ``app.processors.extractor`` path remains as a
  re-export shim so test ``patch`` targets stay valid.
* ``domains/ingest/keywords/matcher.py`` — moved from
  ``app.processors.keyword_matcher`` in Phase 3 step 4
  (regex/contains/exact match with ReDoS guards, highlight, context
  snippets). Legacy path is a re-export shim.
* ``domains/ingest/keywords/rules.py`` — moved from
  ``app.services.keyword_rules`` in Phase 3 step 4
  (normalize/dedupe/identity-key + bilingual ``build_equivalent_terms``).
  Legacy path is a re-export shim. The bilingual expansion calls
  ``app.platform.llm.translator.Translator`` lazily inside the function — at
  module-import time the ingest domain stays free of any LLM dependency,
  keeping the Phase 3 boundary check clean.
* ``domains/ingest/content_processor.py`` — moved from the legacy
  processors package in Phase 7 (raw item → ORM Content conversion,
  keyword matching, cookie full-text fallback). The legacy processors
  path is now a re-export shim; manual reprocess compatibility still
  resolves summariser/translator handles lazily.
* ``domains/ingest/search.py`` — moved from
  ``app.utils.fts_query`` in Phase 3 step 6 (SQLite FTS5 MATCH
  expression builder; sanitizes user input before hitting the
  ``content_fts`` virtual table that ingest populates via
  ``StorageStage``). Legacy ``app.utils.fts_query`` path is a
  re-export shim.
* ``domains/ingest/cleanup.py`` — moved from
  ``app.api.contents_cleanup`` in Phase 3 step 7 (low-signal /
  junk-row cleanup helpers that re-apply the same
  ``get_website_content_reject_reason`` filter ingest uses on raw
  items). The FastAPI route handlers stay in
  ``app.api.contents_cleanup`` and re-import the helpers from this
  module, so the existing
  ``api.contents → api.contents_cleanup`` re-export chain that
  ``tests/test_content_quality_filters.py`` relies on stays intact.
* ``domains/ingest/finish.py`` — moved from the legacy
  ``app.tasks.process_tasks.process_new_content`` in Phase 3 step 5
  (post-fetch non-LLM finalization: cookie full-text top-up + keyword
  matching + quality-metadata stamp + baseline scoring + keyword-alert
  dispatch). Function was renamed ``finish_content`` to match the
  blueprint's ingest vocabulary; Phase 7 retired the legacy
  ``process_new_content`` / ``_process_new_content_async`` /
  ``_dispatch_keyword_alerts`` re-exports together with
  ``BoundedTaskQueue.enqueue_process``.
  :meth:`BoundedTaskQueue.enqueue_ingest_finish` is the canonical
  dispatch method.

The ingest domain MUST NOT import LLM providers, the summariser or the
translator; that boundary is enforced by ``check_domain_imports.py`` from
Phase 3 onwards.
"""
