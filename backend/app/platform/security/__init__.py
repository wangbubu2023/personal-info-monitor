"""Platform-level security primitives.

Phase 5 step 3 of the refactor relocates cross-cutting security helpers
out of ``app.utils`` into the platform layer:

* :mod:`app.platform.security.encryption` — Fernet symmetric encryption
  used to seal opaque credential blobs (API keys, cookies, auth secrets)
  before persistence. Previously at ``app.utils.encryption``.
* :mod:`app.platform.security.ssrf` — outbound SSRF guard
  (``assert_public_http_target`` / ``check_before_fetch``) used by every
  collector that does network IO. Previously at ``app.utils.ssrf``.

The ``app.utils.encryption`` shim remains because it still serves as a
``patch()`` target in several tests. The ``app.utils.ssrf`` shim was
retired by the post-Phase-7 audit; the import-boundary checker bans it.
SSRF callers must import :mod:`app.platform.security.ssrf` directly.
"""
