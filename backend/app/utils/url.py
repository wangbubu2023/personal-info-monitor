"""URL/host normalization helpers."""

import hashlib
import re
from urllib.parse import parse_qs, parse_qsl, urlencode, urlparse, urlunparse

_SCHEME_RE = re.compile(r"^https?://", re.IGNORECASE)
_DATE_YYYYMMDD_RE = re.compile(r"^(?:19|20)\d{6}$")
_TRACKING_QUERY_KEYS = {
    "fbclid",
    "from",
    "gclid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "mkt_tok",
    "ref",
    "source",
    "spm",
    "vero_id",
    "yclid",
}
_ARTICLE_HUB_SEGMENTS = {
    "article",
    "articles",
    "blog",
    "blogs",
    "news",
    "post",
    "posts",
    "story",
    "stories",
}


def _normalized_host_with_port(parsed) -> str:
    host = (parsed.hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if host.startswith("amp."):
        host = host[4:]
    port = parsed.port
    if port and not ((parsed.scheme.lower() == "http" and port == 80) or (parsed.scheme.lower() == "https" and port == 443)):
        return f"{host}:{port}"
    return host


def _normalized_path(path: str | None) -> str:
    raw = re.sub(r"/+", "/", path or "")
    if raw in ("", "/"):
        return "/"
    parts = [part for part in raw.split("/") if part]
    if parts and parts[0].lower() == "amp":
        parts = parts[1:]
    if parts and parts[-1].lower() == "amp":
        parts = parts[:-1]
    if not parts:
        return "/"
    return "/" + "/".join(parts)


def _normalized_query(query: str | None) -> str:
    if not query:
        return ""
    kept = []
    for key, value in parse_qsl(query, keep_blank_values=True):
        lower_key = key.lower()
        if lower_key.startswith("utm_") or lower_key in _TRACKING_QUERY_KEYS:
            continue
        kept.append((key, value))
    return urlencode(sorted(kept), doseq=True)


def _canonical_url_parts(url: str) -> tuple[str, str, str, str] | None:
    p = urlparse(url)
    if not p.scheme or not p.netloc:
        return None
    host = _normalized_host_with_port(p)
    path = _normalized_path(p.path)
    query = _normalized_query(p.query)
    return ("https", host, path, query)


def _looks_like_article_id_segment(parts: list[str], index: int) -> bool:
    part = parts[index]
    if not part.isdigit() or len(part) < 5 or _DATE_YYYYMMDD_RE.match(part):
        return False
    prev = parts[index - 1].lower() if index > 0 else ""
    next_part = parts[index + 1].lower() if index + 1 < len(parts) else ""
    if prev in _ARTICLE_HUB_SEGMENTS:
        return True
    if not next_part:
        return True
    return bool(re.search(r"[a-z]", next_part)) and len(next_part) >= 8


def normalize_source_url_input(url: str | None) -> str:
    """Normalize user-entered monitoring URLs (prepend https:// when scheme omitted)."""
    s = (url or "").strip()
    if not s:
        return ""
    if not _SCHEME_RE.match(s):
        s = f"https://{s}"
    return s


def canonical_article_external_id(url: str | None) -> str:
    """Map article URLs that point at the same story to one stable external_id key.

    Handles common WordPress patterns (``?p=12345`` vs slug paths containing the
    same numeric post id) so RSS and website listing fetches dedupe correctly.
    """
    s = (url or "").strip()
    if not s:
        return ""
    if not _SCHEME_RE.match(s):
        return s
    p = urlparse(s)
    if not p.scheme or not p.netloc:
        return s.lower()
    host = _normalized_host_with_port(p)

    wp_id = (parse_qs(p.query).get("p") or [None])[0]
    if wp_id and str(wp_id).strip().isdigit():
        return f"https://{host}/article:{str(wp_id).strip()}"

    parts = [part for part in _normalized_path(p.path).split("/") if part]
    for idx, part in enumerate(parts):
        if _looks_like_article_id_segment(parts, idx):
            return f"https://{host}/article:{part}"

    return normalize_source_url_for_dedupe(s)


def normalize_external_id(external_id: str | None) -> str | None:
    """Normalize external_id to fit DB length constraints while staying stable."""
    if not external_id:
        return external_id
    eid = str(external_id).strip()
    if eid.startswith(("http://", "https://")):
        eid = canonical_article_external_id(eid)
    if len(eid) <= 255:
        return eid
    digest = hashlib.sha1(eid.encode("utf-8")).hexdigest()
    return f"hash:{digest}"


def normalize_source_url_for_dedupe(url: str | None) -> str:
    """Canonical URL for monitoring-source duplicate checks.

    Treats ``http://a.com`` and ``https://www.a.com/`` as the same; lowercases
    and normalizes host/path; strips tracking query parameters and fragments.
    Non-tracking query parameters are preserved because distinct feeds or
    article pages may genuinely differ by query.
    """
    s = (url or "").strip()
    if not s:
        return ""
    parts = _canonical_url_parts(s)
    if parts is None:
        return s.lower()
    scheme, host, path, query = parts
    return urlunparse((scheme, host, path, "", query, ""))


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
