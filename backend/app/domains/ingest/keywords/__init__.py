"""Keyword matching + normalization + bilingual equivalents.

Phase 3 step 4 of the module-refactor blueprint pulls keyword logic out
of ``app.processors`` / ``app.services``:

* ``domains/ingest/keywords/matcher.py`` — :class:`KeywordMatcher`
  (regex/contains/exact match, ReDoS guards, highlight, context snippet);
  moved from ``app.processors.keyword_matcher``.
* ``domains/ingest/keywords/rules.py`` — normalize/dedupe/identity-key
  helpers + bilingual ``build_equivalent_terms`` + manual-terms
  normalization; moved from ``app.services.keyword_rules``.

Legacy paths (``app.processors.keyword_matcher``,
``app.services.keyword_rules``) remain as re-export shims through
Phase 7 for out-of-tree callers.

Note: ``rules.build_equivalent_terms`` resolves
``app.platform.llm.translator`` lazily inside the function for bilingual
expansion; that is an enrich/platform dependency (LLM-powered
translation) and stays behind a lazy import so the ingest domain at
module-import time does not touch LLM runtime setup.
"""
