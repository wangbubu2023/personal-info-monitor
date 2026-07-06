"""Content processors package.

Phase 7 retired the legacy re-export bundle that pre-loaded
``Summarizer`` / ``Translator`` / ``ContentExtractor`` / ``KeywordMatcher``
/ ``ContentProcessor`` into this namespace. Importers must address the
canonical modules directly (for example
``app.domains.ingest.content_processor``,
``app.domains.ingest.keywords.matcher`` and ``app.platform.llm.*``).
This package only keeps narrow compatibility shims for old patch
targets.
"""
