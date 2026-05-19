"""Backwards-compatible facade for hourly digest repository helpers.

The implementation has moved to
:mod:`app.domains.enrich.hourly.repository` as part of Phase 4 step 6
of the module-refactor blueprint. This shim re-exports every public
symbol so any out-of-tree consumer still importing
``app.services.hourly_digest.repository`` keeps resolving.
"""

from app.domains.enrich.hourly.repository import *  # noqa: F401,F403 — re-export
