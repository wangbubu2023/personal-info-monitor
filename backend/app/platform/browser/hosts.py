"""Site-family host detection used by browser-session orchestration.

Centralising the ``x.com``/``twitter.com`` equivalence keeps the bootstrap,
validation, and source-binding paths in agreement: a browser session created
for one host must cover the other across all of fetch/auth tooling.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Optional

from app.utils.url import host_matches, normalize_host

_X_HOSTS: frozenset[str] = frozenset({"x.com", "twitter.com"})
X_REQUIRED_AUTH_COOKIES: tuple[str, str] = ("auth_token", "ct0")


def is_x_host(host: Optional[str]) -> bool:
    """Whether ``host`` refers to the X (ex-Twitter) family of sites."""

    return normalize_host(host or "") in _X_HOSTS


def x_auth_cookie_names(cookies: Iterable[Mapping[str, Any]] | None) -> set[str]:
    """Return normalized cookie names scoped to the X/Twitter site family."""

    names: set[str] = set()
    for cookie in cookies or ():
        domain = str(cookie.get("domain") or "")
        if not (
            host_matches(domain, "x.com")
            or host_matches(domain, "twitter.com")
        ):
            continue
        name = str(cookie.get("name") or "").strip().lower()
        if name:
            names.add(name)
    return names


def missing_x_auth_cookies(cookies: Iterable[Mapping[str, Any]] | None) -> list[str]:
    """List the collector-critical X cookies absent from a captured jar."""

    names = x_auth_cookie_names(cookies)
    return [name for name in X_REQUIRED_AUTH_COOKIES if name not in names]


def is_wsj_host(host: Optional[str]) -> bool:
    """Whether ``host`` belongs to The Wall Street Journal."""

    normalized = normalize_host(host or "")
    return normalized == "wsj.com" or normalized.endswith(".wsj.com")
