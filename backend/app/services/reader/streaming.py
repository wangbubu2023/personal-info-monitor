"""Backwards-compatible facade for the reader NDJSON streaming module.

The implementation has moved to
:mod:`app.domains.enrich.reader.streaming` as part of Phase 4 step 5
of the module-refactor blueprint. This shim re-exports every public
symbol so any out-of-tree consumer still importing
``app.services.reader.streaming`` keeps resolving.

Note for test authors: ``patch("app.services.reader.streaming.X", ...)``
patches the **shim**'s local binding, not the canonical module where
the actual call sites live. Patches that need to intercept internal
streaming calls (``_split_for_reader``, ``Translator``, …) must
target ``app.domains.enrich.reader.streaming`` directly.
"""

from app.domains.enrich.reader.streaming import *  # noqa: F401,F403 — re-export
