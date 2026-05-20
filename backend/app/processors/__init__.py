"""Content processors package.

Phase 7 retired the legacy re-export bundle that pre-loaded
``Summarizer`` / ``Translator`` / ``ContentExtractor`` / ``KeywordMatcher``
/ ``ContentProcessor`` into this namespace. Importers must address the
canonical submodule directly (e.g. ``app.processors.content_processor``,
``app.processors.keyword_matcher``). The eventual home of these classes
is :mod:`app.domains.ingest` / :mod:`app.domains.enrich.content` per
blueprint §5.5.
"""
