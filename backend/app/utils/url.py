"""URL/host normalization helpers."""

from urllib.parse import urlparse


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

