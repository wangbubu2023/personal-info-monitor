"""Pure X/Twitter text and URL predicates shared across domains."""

from __future__ import annotations

import re
from urllib.parse import urlparse

X_HOSTS = frozenset({"x.com", "twitter.com", "www.x.com", "www.twitter.com", "mobile.twitter.com"})
X_INTERSTITIAL_MARKERS = (
    "javascript is disabled",
    "enable javascript",
    "switch to a supported browser",
    "supported browser",
    "help center",
    "x corp",
    "terms of service",
)


def is_x_status_page_url(url: str) -> bool:
    """True for tweet permalinks whose plain HTTP body is usually JS boilerplate."""
    try:
        parsed = urlparse((url or "").strip())
        host = (parsed.hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        return host in X_HOSTS and "/status/" in (parsed.path or "")
    except Exception:  # noqa: BLE001 - urlparse should not raise; stay defensive
        return False


def looks_like_x_interstitial_text(text: str) -> bool:
    """Detect X noscript / login-wall boilerplate mistaken for article body."""
    normalized = re.sub(r"\s+", " ", (text or "").strip().lower())
    if not normalized:
        return False
    hits = sum(1 for marker in X_INTERSTITIAL_MARKERS if marker in normalized)
    if hits >= 3:
        return True
    return "javascript is disabled" in normalized and "x.com" in normalized
