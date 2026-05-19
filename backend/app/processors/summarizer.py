"""Backwards-compatible facade for the summariser.

The implementation has moved to :mod:`app.platform.llm.summarizer` as
part of Phase 4 step 3 of the module-refactor blueprint. This shim
re-exports every public symbol so any out-of-tree consumer still
importing ``app.processors.summarizer`` keeps resolving.

Note for test authors: ``patch("app.processors.summarizer.X", ...)``
patches the **shim**'s local binding, not the canonical module where
the actual call sites live. Patches that need to intercept internals
(``get_settings``, ``get_system_settings_sync``,
``enrich_model_settings_from_api_config``, …) must target
``app.platform.llm.summarizer`` directly.
"""

from app.platform.llm.summarizer import *  # noqa: F401,F403 — re-export
