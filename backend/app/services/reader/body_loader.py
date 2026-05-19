"""Backwards-compatible facade for the reader body-loader.

The implementation has moved to
:mod:`app.domains.enrich.reader.body_loader` as part of Phase 4 step 5
of the module-refactor blueprint. This shim re-exports every public
symbol so any out-of-tree consumer still importing
``app.services.reader.body_loader`` keeps resolving.

Note for test authors: ``patch("app.services.reader.body_loader.X", ...)``
patches the **shim**'s local binding, not the canonical module where
the actual call sites live. Patches that need to intercept internal
``body_loader`` calls (e.g. ``aiohttp.ClientSession``,
``assert_public_http_target``, ``ContentExtractor``,
``_clean_x_reader_body``, ``_extract_x_article_url``, …) must target
``app.domains.enrich.reader.body_loader`` directly.
"""

from app.domains.enrich.reader.body_loader import *  # noqa: F401,F403 — re-export
