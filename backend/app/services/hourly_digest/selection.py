"""Backwards-compatible facade for hourly digest selection logic.

The implementation has moved to
:mod:`app.domains.enrich.hourly.selection` as part of Phase 4 step 6
of the module-refactor blueprint. This shim re-exports every public
symbol so any out-of-tree consumer still importing
``app.services.hourly_digest.selection`` keeps resolving.
"""

from app.domains.enrich.hourly.selection import *  # noqa: F401,F403 — re-export
