"""Backwards-compatible facade for the reader sub-domain.

Phase 4 step 5 of the module-refactor blueprint moved the reader
implementation into :mod:`app.domains.enrich.reader`. This package
now contains only thin re-export shims (``body_loader``,
``translation``, ``streaming``) so any out-of-tree consumer importing
``app.services.reader.<module>`` keeps resolving; the
``app/api/contents_reader.py`` HTTP layer was updated to import from
the canonical location.

Phase 7 will retire this facade entirely.
"""
