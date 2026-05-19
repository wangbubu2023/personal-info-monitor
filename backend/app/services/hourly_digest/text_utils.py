"""Backwards-compatible facade for hourly digest text utilities.

The implementation has moved to
:mod:`app.domains.enrich.hourly.text_utils` as part of Phase 4 step 6
of the module-refactor blueprint. This shim re-exports every public
symbol so any out-of-tree consumer still importing
``app.services.hourly_digest.text_utils`` keeps resolving.

Note for test authors: ``patch("app.services.hourly_digest.text_utils.X", ...)``
patches the **shim**'s local binding, not the canonical module where
the actual call sites live. Patches that need to intercept internals
(e.g. ``get_system_settings_sync``) must target
``app.domains.enrich.hourly.text_utils`` directly.
"""

from app.domains.enrich.hourly.text_utils import *  # noqa: F401,F403 — re-export
