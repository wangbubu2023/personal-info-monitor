"""Platform-level configuration primitives.

Phase 5 of the refactor relocates the application's configuration layer
into the platform package. As of Phase 5 step 10 this includes:

* :mod:`app.platform.config.settings` — canonical home for the
  environment-driven ``Settings`` model, the cached ``get_settings``
  accessor, the runtime-secrets bootstrap, and the CORS origin parser.
  Previously lived at ``app.config``; that module is preserved as a
  re-export shim through Phase 7.
* :mod:`app.platform.config.system_settings` — DB-backed user-tunable
  settings + in-memory cache + hourly-digest prompt helpers. Previously
  lived at ``app.services.system_settings`` (also kept as a shim).

Future siblings planned under this package:

* ``platform.config.features`` — eventual destination for
  ``app.features`` runtime flags.
"""
