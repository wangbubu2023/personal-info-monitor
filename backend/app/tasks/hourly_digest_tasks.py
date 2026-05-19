"""Backwards-compatible facade for the hourly digest orchestrator.

The implementation has moved to :mod:`app.domains.enrich.hourly.tasks`
as part of Phase 4 step 6 of the module-refactor blueprint. This shim
re-exports every public symbol so any out-of-tree consumer still
importing ``app.tasks.hourly_digest_tasks`` keeps resolving.

Note: ``_foo`` underscore-prefixed legacy aliases (``_build_prompt``,
``_get_digest_limits``, …) are **not** carried by ``import *`` and
therefore are not present on this shim. In-tree tests that previously
accessed ``hourly_digest_tasks._foo`` were migrated to import from the
canonical ``app.domains.enrich.hourly.tasks`` module directly.
"""

from app.domains.enrich.hourly.tasks import *  # noqa: F401,F403 — re-export
