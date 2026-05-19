"""URL/host normalization helpers."""

import re
from urllib.parse import urlparse, urlunparse

_SCHEME_RE = re.compile(r"^https?://", re.IGNORECASE)


def normalize_source_url_input(url: str | None) -> str:
    """Normalize user-entered monitoring URLs (prepend https:// when scheme omitted)."""
    s = (url or "").strip()
    if not s:
        return ""
    if not _SCHEME_RE.match(s):
        s = f"https://{s}"
    return s


def normalize_source_url_for_dedupe(url: str | None) -> str:
    """Canonical URL for monitoring-source duplicate checks.

    Treats ``https://a.com`` and ``https://a.com/`` as the same; lowercases scheme and host;
    normalizes root path. Query string is preserved (distinct feeds may differ only by query).
    """
    s = (url or "").strip()
    if not s:
        return ""
    p = urlparse(s)
    if not p.scheme or not p.netloc:
        return s.lower()
    scheme = p.scheme.lower()
    netloc = p.netloc.lower()
    path = p.path or ""
    if path in ("", "/"):
        canon_path = "/"
    else:
        canon_path = "/" + path.strip("/").replace("//", "/")
    return urlunparse((scheme, netloc, canon_path, "", p.query, ""))


def normalize_host(url_or_host: str | None) -> str:
    """Normalize URL or host to lowercase host without leading www."""
    raw = (url_or_host or "").strip().lower()
    if not raw:
        return ""
    if "://" not in raw:
        raw = f"https://{raw}"
    host = (urlparse(raw).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def host_matches(left: str | None, right: str | None) -> bool:
    """Host match with subdomain awareness."""
    a = normalize_host(left)
    b = normalize_host(right)
    if not a or not b:
        return False
    return a == b or a.endswith("." + b) or b.endswith("." + a)

