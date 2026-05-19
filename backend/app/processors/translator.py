"""Backwards-compatible facade for the translator.

The implementation has moved to :mod:`app.platform.llm.translator` as
part of Phase 4 step 3 of the module-refactor blueprint. This shim
re-exports every public symbol so any out-of-tree consumer still
importing ``app.processors.translator`` keeps resolving.

Note for test authors: ``patch("app.processors.translator.X", ...)``
patches the **shim**'s local binding, not the canonical module where
the actual call sites live. Patches that need to intercept internals
(``get_settings``, ``ModelProviderClient``,
``get_translation_settings``, ``is_translation_cloud_fallback_enabled``,
``get_translation_fallback_model_settings``,
``get_translation_cloud_fallback_openai_settings``, …) must target
``app.platform.llm.translator`` directly.
"""

from app.platform.llm.translator import *  # noqa: F401,F403 — re-export
