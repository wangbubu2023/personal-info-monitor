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
Phase 7 so existing test ``monkeypatch.setattr`` / ``patch`` targets and
external callers (``processors/content_processor.py``,
``api/keywords.py``, ``tasks/process_tasks.py``,
``pipeline/coordinator.py``, ``alembic`` migration) keep working.

Note: ``rules.build_equivalent_terms`` does ``from app.processors.translator
import Translator`` lazily inside the function for bilingual expansion;
that is an *enrich* dependency (LLM-powered translation) and stays
behind a lazy import so the ingest domain at module-import time does
not touch ``processors.translator``.
"""
