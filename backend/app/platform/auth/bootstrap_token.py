"""``/local-token`` endpoint and SPA bootstrap-token utilities.

Phase 5 step 14 of the refactor pulls the ``/local-token`` endpoint and
its supporting helpers out of :mod:`app.main` so the FastAPI entry module
stops carrying inline authentication-bootstrapping logic. The endpoint
hands the long-lived API key (``settings.pim_api_key``) to *trusted local
callers only*; every request must pass four independent defence-in-depth
gates:

1. Source IP must be loopback (``127.0.0.1`` / ``::1``) — verified through
   :func:`app.middleware.api_rate_limit.get_real_client_ip`, which honours
   the trusted-proxy configuration.
2. ``Host`` header must be ``localhost``/``127.0.0.1``/``::1``/``[::1]``
   to block DNS-rebinding attacks where a malicious site coerces the
   browser into hitting the loopback interface under its own domain.
3. ``Origin`` header (when present) must be CORS-whitelisted or the
   Tauri shell scheme — ``null`` and arbitrary remote origins are
   rejected; a missing ``Origin`` is acceptable because it implies a
   server-side/non-browser caller (curl, the operator CLI), which the
   other gates still cover.
4. A ``bootstrap_token`` (query string or ``X-Bootstrap-Token`` header)
   must match the value stored in ``runtime-secrets.json`` (file mode
   0600). The token is distributed out-of-band to the Tauri shell and
   the operator CLI and is never echoed over HTTP.

In addition to the endpoint, this module exposes
:func:`inject_bootstrap_meta`, which stamps the bootstrap token into
``index.html`` for trusted loopback callers so the SPA shell can silently
acquire its API key on first paint instead of prompting the user. The
same defence-in-depth gates apply: remote callers and Host-spoofed
requests receive an unmodified ``index.html``.
"""

from __future__ import annotations

import secrets as _secrets
from html import escape as _html_escape

from fastapi import APIRouter, HTTPException, Request

from app.middleware.api_rate_limit import get_real_client_ip
from app.platform.config.settings import get_settings, parse_cors_origins
from app.platform.observability.logger import get_logger

logger = get_logger(__name__)

ALLOWED_LOCAL_TOKEN_HOSTNAMES = frozenset(
    {"127.0.0.1", "localhost", "::1", "[::1]"}
)

BOOTSTRAP_META_NAME = "pim-bootstrap-token"

# Legacy alias kept for tests/external scripts that still import the
# underscore-prefixed constant (introduced before Phase 5.14 moved the
# helpers here from ``app.main``).
_ALLOWED_LOCAL_TOKEN_HOSTNAMES = ALLOWED_LOCAL_TOKEN_HOSTNAMES
_BOOTSTRAP_META_NAME = BOOTSTRAP_META_NAME


def _hostname_of(host_header: str | None) -> str:
    """Strip an optional ``:port`` from a Host header and lower-case."""
    value = (host_header or "").strip().lower()
    if not value:
        return ""
    # IPv6 literal like "[::1]:8000"
    if value.startswith("["):
        closing = value.find("]")
        if closing == -1:
            return value
        return value[: closing + 1]
    # host:port
    if value.count(":") == 1:
        return value.split(":", 1)[0]
    return value


def _origin_is_permitted(origin: str | None) -> bool:
    """Only same-site or Tauri origins may call the bootstrap endpoint."""
    candidate = (origin or "").strip().lower()
    if not candidate:
        return True
    if candidate == "tauri://localhost":
        return True
    allowed = {item.lower() for item in parse_cors_origins(get_settings().cors_origins)}
    return candidate in allowed


def _bootstrap_token_matches(request: Request) -> bool:
    """Return True iff the request carries the configured bootstrap token."""
    expected = (get_settings().bootstrap_token or "").strip()
    if not expected:
        # Fail closed: a misconfigured server should not hand out API keys.
        return False

    header_token = request.headers.get("X-Bootstrap-Token", "")
    query_token = request.query_params.get("bootstrap_token", "")
    for provided in (header_token, query_token):
        provided = (provided or "").strip()
        if provided and _secrets.compare_digest(provided, expected):
            return True
    return False


def _inject_bootstrap_meta(html: str, request: Request, token: str) -> str:
    """Stamp the bootstrap token into ``index.html`` for trusted loopback callers."""
    clean_token = (token or "").strip()
    if not clean_token:
        return html
    try:
        real_ip = get_real_client_ip(request)
    except Exception:  # noqa: BLE001 - we never want injection to throw upstream
        return html
    if real_ip not in ("127.0.0.1", "::1"):
        return html
    hostname = _hostname_of(request.headers.get("host"))
    if hostname not in ALLOWED_LOCAL_TOKEN_HOSTNAMES:
        return html
    meta_tag = (
        f'<meta name="{BOOTSTRAP_META_NAME}" '
        f'content="{_html_escape(clean_token, quote=True)}">'
    )
    if "</head>" in html:
        return html.replace("</head>", f"    {meta_tag}\n  </head>", 1)
    return meta_tag + html


# Public alias — callers should reach for this name; ``_inject_bootstrap_meta``
# stays exported for backward compatibility with tests that imported the
# underscore name from ``app.main`` before the move.
inject_bootstrap_meta = _inject_bootstrap_meta


bootstrap_router = APIRouter(tags=["bootstrap"])


@bootstrap_router.get("/local-token")
async def local_token(request: Request) -> dict[str, str]:
    """Return the API key for trusted local callers only.

    See the module docstring for the four defence-in-depth gates this
    endpoint enforces.
    """
    real_ip = get_real_client_ip(request)
    if real_ip not in ("127.0.0.1", "::1"):
        raise HTTPException(status_code=403, detail="Local access only")

    hostname = _hostname_of(request.headers.get("host"))
    if hostname not in ALLOWED_LOCAL_TOKEN_HOSTNAMES:
        logger.warning("/local-token rejected: invalid Host header %r", request.headers.get("host"))
        raise HTTPException(status_code=403, detail="Invalid host")

    if not _origin_is_permitted(request.headers.get("origin")):
        logger.warning("/local-token rejected: invalid Origin %r", request.headers.get("origin"))
        raise HTTPException(status_code=403, detail="Invalid origin")

    if not _bootstrap_token_matches(request):
        logger.warning("/local-token rejected: missing or invalid bootstrap token")
        raise HTTPException(status_code=401, detail="Missing or invalid bootstrap token")

    return {"api_key": get_settings().pim_api_key}
