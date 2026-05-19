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
* ``domains/ingest/build_content.py`` — moved from
  ``app.pipeline.coordinator._build_raw_content_objects`` in Phase 3 step 3
  (the LLM-free portion of the raw → ORM Content build). The legacy private
  name still resolves through ``app.pipeline.coordinator`` as a re-export
  shim; wrapper-internal helpers (``strip_html_tags`` etc.) live next to the
  implementation and must be patched at
  ``app.domains.ingest.build_content.<name>``.
* ``domains/ingest/extractor.py`` — moved from
  ``app.processors.extractor`` in Phase 3 step 4 (HTML → main-content
  text extraction; readability + trafilatura + BeautifulSoup
  fallbacks). The legacy ``app.processors.extractor`` path remains as a
  re-export shim so test ``patch`` targets stay valid.
* ``domains/ingest/keywords/``, ``scoring.py`` — to be moved from
  ``app/processors`` and ``app/services`` in the remaining Phase 3
  step-4 cuts.

The ingest domain MUST NOT import LLM providers, the summariser or the
translator; that boundary is enforced by ``check_domain_imports.py`` from
Phase 3 onwards.
"""
