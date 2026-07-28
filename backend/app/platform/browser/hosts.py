"""Site-family host detection used by browser-session orchestration.

Centralising the ``x.com``/``twitter.com`` equivalence keeps the bootstrap,
validation, and source-binding paths in agreement: a browser session created
for one host must cover the other across all of fetch/auth tooling.
"""

from __future__ import annotations

from typing import Optional

from app.utils.url import normalize_host

_X_HOSTS: frozenset[str] = frozenset({"x.com", "twitter.com"})
def is_x_host(host: Optional[str]) -> bool:
    """Whether ``host`` refers to the X (ex-Twitter) family of sites."""

    return normalize_host(host or "") in _X_HOSTS


def is_wsj_host(host: Optional[str]) -> bool:
    """Whether ``host`` belongs to The Wall Street Journal."""

    normalized = normalize_host(host or "")
    return normalized == "wsj.com" or normalized.endswith(".wsj.com")
