"""Dedup, quality, keyword match, scoring, persistence.

Phase 3 of the refactor consolidates the post-collection / pre-LLM logic
here:

* ``domains/ingest/quality.py`` — owns
  ``get_website_content_reject_reason`` (currently in ``pipeline/utils.py``,
  imported by ``normalizer_stage``, ``coordinator``,
  ``collectors/website_parser`` and ``api/contents_cleanup``)
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
* ``domains/ingest/extractor.py``, ``keywords/`` — moved from
  ``app/processors``

The ingest domain MUST NOT import LLM providers, the summariser or the
translator; that boundary is enforced by ``check_domain_imports.py`` from
Phase 3 onwards.
"""
