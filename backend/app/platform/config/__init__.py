"""Platform-level configuration primitives.

Phase 5 step 2 of the refactor relocates ``app.services.system_settings``
(DB-backed user-tunable settings + in-memory cache + hourly-digest prompt
helpers) into the platform layer. The legacy
:mod:`app.services.system_settings` path remains as a re-export shim
through Phase 7 so existing imports (and the dozens of
``patch("app.services.system_settings.*")`` references) keep working
while we migrate callers one at a time.

Future siblings of :mod:`app.platform.config.system_settings` planned
under this package:

* ``platform.config.settings`` — eventual destination for ``app.config``
  (``Settings`` / ``get_settings`` / ``ENRICH_*`` toggles).
* ``platform.config.features`` — eventual destination for
  ``app.features`` runtime flags.
"""
