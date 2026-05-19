"""Shared defaults for aiohttp client sessions.

Modern sites (X/Twitter, NYT, WSJ, Cloudflare-fronted origins…) frequently
emit HTTP response headers — Content-Security-Policy, Report-To,
Permissions-Policy, multiple ``Set-Cookie`` chains — that exceed aiohttp's
stock 8190-byte line/field limits. When that happens the underlying HTTP
parser aborts with::

    ValueError: Got more than 8190 bytes (NNNN) when reading Header value is too long.

and the caller sees the request fail before the body is ever touched.

``permissive_session_kwargs`` bundles safer defaults (``max_line_size`` and
``max_field_size`` raised to 64 KiB) so callers can opt in with one line
while still overriding any kwarg (timeout, headers, cookie_jar, …). 64 KiB
is comfortably above the largest headers observed in practice and well
within aiohttp's supported range.
"""

from __future__ import annotations

from typing import Any, Dict

# ~64 KiB: large enough to absorb any real-world header we've seen from
# X/NYT/WSJ/Cloudflare, small enough to keep memory overhead negligible.
LARGE_HEADER_LIMIT = 64 * 1024


def permissive_session_kwargs(**overrides: Any) -> Dict[str, Any]:
    """Return kwargs for :class:`aiohttp.ClientSession` with relaxed header limits.

    Caller-supplied ``overrides`` win over the defaults so existing
    ``timeout=``/``headers=``/``cookie_jar=`` arguments continue to work::

        async with aiohttp.ClientSession(
            **permissive_session_kwargs(timeout=timeout, cookie_jar=jar)
        ) as session:
            ...
    """
    kwargs: Dict[str, Any] = {
        "max_line_size": LARGE_HEADER_LIMIT,
        "max_field_size": LARGE_HEADER_LIMIT,
    }
    kwargs.update(overrides)
    return kwargs


__all__ = ["LARGE_HEADER_LIMIT", "permissive_session_kwargs"]
