"""Backwards-compatible facade for hourly digest synthesis logic.

The implementation has moved to
:mod:`app.domains.enrich.hourly.synthesis` as part of Phase 4 step 6
of the module-refactor blueprint. This shim re-exports every public
symbol so any out-of-tree consumer still importing
``app.services.hourly_digest.synthesis`` keeps resolving.

Note for test authors: ``patch("app.services.hourly_digest.synthesis.X", ...)``
patches the **shim**'s local binding, not the canonical module where
the actual call sites live. Patches that need to intercept internals
(e.g. ``Translator``) must target
``app.domains.enrich.hourly.synthesis`` directly.
"""

from app.domains.enrich.hourly.synthesis import *  # noqa: F401,F403 — re-export
