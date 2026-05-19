"""Backwards-compatible facade for the reader translation orchestration.

The implementation has moved to
:mod:`app.domains.enrich.reader.translation` as part of Phase 4 step 5
of the module-refactor blueprint. This shim re-exports every public
symbol so any out-of-tree consumer still importing
``app.services.reader.translation`` keeps resolving.

Note for test authors: ``patch("app.services.reader.translation.X", ...)``
patches the **shim**'s local binding, not the canonical module where
the actual call sites live. Patches that need to intercept internal
translation calls (``Translator``, ``_is_valid_translation_text``,
``_is_valid_title_translation``, ``_split_for_reader``, …) must
target ``app.domains.enrich.reader.translation`` directly.
"""

from app.domains.enrich.reader.translation import *  # noqa: F401,F403 — re-export
