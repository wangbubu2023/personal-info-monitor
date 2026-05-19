"""Backwards-compatible facade for the hourly digest pipeline.

Phase 4 step 6 of the module-refactor blueprint moved the implementation
into :mod:`app.domains.enrich.hourly`. This package now contains only
thin re-export shims (``text_utils``, ``selection``, ``synthesis``,
``repository``) so any out-of-tree consumer importing
``app.services.hourly_digest.<module>`` keeps resolving.

Phase 7 will retire this facade entirely.
"""
