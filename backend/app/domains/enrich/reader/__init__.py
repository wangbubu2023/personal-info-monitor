"""Reader sub-domain — body extraction, paragraph split, translation orchestration.

Phase 4 step 1 of the module-refactor blueprint relocates the reader's
shared helpers from ``app.api.content_shared`` (which the
``app/services/reader/*`` modules were reverse-depending on) into
:mod:`app.domains.enrich.reader.shared`. The HTTP-layer
``app.api.content_shared`` module keeps the same public symbols as
re-exports through Phase 7 so existing imports keep resolving.

Future cuts will move ``app/services/reader/{body_loader, streaming,
translation}`` themselves into this package (Phase 4 step 5).
"""
