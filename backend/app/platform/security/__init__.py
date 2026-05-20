"""Platform-level security primitives.

Phase 5 step 3 of the refactor relocates cross-cutting security helpers
out of ``app.utils`` into the platform layer:

* :mod:`app.platform.security.encryption` — Fernet symmetric encryption
  used to seal opaque credential blobs (API keys, cookies, auth secrets)
  before persistence. Previously at ``app.utils.encryption``.
* :mod:`app.platform.security.ssrf` — outbound SSRF guard
  (``assert_public_http_target`` / ``check_before_fetch``) used by every
  collector that does network IO. Previously at ``app.utils.ssrf``.

Both old paths remain as re-export shims (with explicit underscore-symbol
forwarding so existing ``patch("app.utils.ssrf._resolve_host_addresses")``
test sites keep targeting the same symbol identity). Phase 7 removes
those shims.
"""
