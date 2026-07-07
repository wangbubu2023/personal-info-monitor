"""Pure helpers for :mod:`app.domains.fetch.collectors.website`.

All functions here are safe to call without a :class:`WebsiteCollector`
instance — they only depend on URL shape, cookie maps, or primitive browser
session payloads. Moving them out keeps the collector focused on fetch
orchestration and hydration state machines.
"""

from __future__ import annotations

from copy import copy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlparse

from app.utils.cookies import cookie_domains_for_host
from app.utils.datetime import utcnow_naive
from app.utils.logger import get_logger

logger = get_logger(__name__)


def wsj_fallback_rss(website_url: str) -> Optional[str]:
    """Build a fresh WSJ fallback RSS using Google News site search."""
    host = (urlparse(website_url).hostname or "").lower()
    if "wsj.com" not in host:
        return None
    q = quote("site:wsj.com")
    return f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"


def economist_fallback_rss(website_url: str) -> Optional[str]:
    """Build Economist fallback RSS for root/topic URLs that are often challenge-protected."""
    parsed = urlparse(website_url)
    host = (parsed.hostname or "").lower()
    if "economist.com" not in host:
        return None

    path = (parsed.path or "/").strip("/").lower()
    if not path:
        return "https://www.economist.com/international/rss.xml"

    topic_map = {
        "china": "https://www.economist.com/china/rss.xml",
        "business": "https://www.economist.com/business/rss.xml",
        "finance-and-economics": "https://www.economist.com/finance-and-economics/rss.xml",
        "artificial-intelligence": "https://www.economist.com/science-and-technology/rss.xml",
    }
    if path.startswith("topics/"):
        topic = path.split("/", 2)[1] if len(path.split("/", 2)) > 1 else ""
        return topic_map.get(topic, "https://www.economist.com/international/rss.xml")

    section = path.split("/", 1)[0]
    if not section:
        return "https://www.economist.com/international/rss.xml"
    return f"https://www.economist.com/{section}/rss.xml"


def source_with_url(source, url: str):
    """Return a shallow copy of ``source`` with :attr:`url` overridden."""
    cloned = copy(source)
    cloned.url = url
    return cloned


def is_stale_rss_content(contents: List[Dict[str, Any]], max_age_days: int = 3) -> bool:
    """Whether RSS content is stale by latest ``publish_time``."""
    if not contents:
        return True
    latest: Optional[datetime] = None
    for item in contents:
        pt = item.get("publish_time")
        if isinstance(pt, datetime):
            if not latest or pt > latest:
                latest = pt
    if not latest:
        return False
    age = utcnow_naive() - latest
    return age.days >= max_age_days


def _strip_www_prefix(host: str) -> str:
    return host[4:] if host.startswith("www.") else host


_MULTI_LABEL_PUBLIC_SUFFIXES = {
    "co.uk",
    "com.au",
    "com.cn",
    "com.hk",
    "com.sg",
    "com.tw",
    "co.jp",
    "co.kr",
}


def _registrable_domain(host: str) -> str:
    parts = [part for part in host.lower().rstrip(".").split(".") if part]
    if len(parts) < 2:
        return host
    suffix = ".".join(parts[-2:])
    if suffix in _MULTI_LABEL_PUBLIC_SUFFIXES and len(parts) >= 3:
        return ".".join(parts[-3:])
    return suffix


def same_site(source_url: str, candidate_url: str) -> bool:
    source_host = _strip_www_prefix((urlparse(source_url).hostname or "").lower())
    candidate_host = _strip_www_prefix((urlparse(candidate_url).hostname or "").lower())
    if not source_host or not candidate_host:
        return False
    if candidate_host == source_host or candidate_host.endswith("." + source_host):
        return True
    return _registrable_domain(source_host) == _registrable_domain(candidate_host)


# Path segments that strongly signal the following segment is an article slug,
# e.g. ``/zhongwen/articles/<slug>/simp``. These hubs are often followed by
# plain-word slugs such as ``/blog/hello``.
ARTICLE_HUB_SEGMENTS = {
    "articles",
    "article",
    "blog",
    "story",
    "stories",
}


def _looks_like_slug_segment(segment: str) -> bool:
    return "-" in segment or "." in segment or any(c.isdigit() for c in segment)


def is_google_news_wrapper(article_url: str) -> bool:
    try:
        parsed = urlparse(article_url)
        host = (parsed.hostname or "").lower()
        path = parsed.path or ""
        return host == "news.google.com" and "/rss/articles/" in path
    except Exception as exc:  # noqa: BLE001 - URL libs can raise diverse errors
        logger.warning("Failed to inspect Google News wrapper URL %s: %s", article_url, exc)
        return False


def looks_like_article_url(source_url: str, candidate_url: str) -> bool:
    """Heuristic check for an article-shaped URL on the same site."""
    if is_google_news_wrapper(candidate_url):
        return True
    if not candidate_url or not same_site(source_url, candidate_url):
        return False
    parsed = urlparse(candidate_url)
    path = (parsed.path or "").strip().lower()
    if not path or path == "/":
        return False
    non_article_prefixes = (
        "/video",
        "/videos",
        "/podcasts",
        "/newsletters",
        "/livecoverage",
        "/live",
        "/search",
        "/topics",
        "/topic",
        "/tag",
        "/tags",
        "/authors",
        "/author",
        "/account",
        "/subscribe",
        "/login",
        "/signin",
        "/category",
        "/list",
        "/channel",
        "/channels",
        "/special",
        "/zhuanti",
        "/fenlei",
        "/pindao",
    )
    if any(path.startswith(prefix) for prefix in non_article_prefixes):
        return False

    segments = [s for s in path.split("/") if s]
    if len(segments) < 1:
        return False

    # An article-hub segment (``articles``/``story``/``blog``/...) followed by
    # another segment is a strong article signal. A trailing locale variant
    # (``simp``/``trad``) or ``amp`` marker must not cause a reject.
    for index, segment in enumerate(segments[:-1]):
        if segment in ARTICLE_HUB_SEGMENTS and segments[index + 1]:
            return True

    tail = segments[-1]
    # A bare tail without slug markers (dashes / dots / digits) typically
    # belongs to a section hub page rather than a specific article.
    if "-" not in tail and "." not in tail and not any(c.isdigit() for c in tail):
        return False

    return True


def has_browser_session(runtime_session: Optional[Dict[str, Any]]) -> bool:
    return bool(runtime_session and str(runtime_session.get("user_data_dir") or "").strip())


def browser_session_auth_ready(runtime_session: Optional[Dict[str, Any]]) -> bool:
    """Whether a browser session should be trusted for automated page fetches.

    Older runtime payloads did not include ``auth_ready``. Treat a missing key
    as usable for compatibility, but honor an explicit ``False`` from the
    auth-helper validation chain so stale profiles do not keep launching
    Chromium for guaranteed-failing paywall hydration.
    """
    return bool(has_browser_session(runtime_session) and runtime_session.get("auth_ready") is not False)


def storage_state_path_for_playwright(browser_session: Optional[Dict[str, Any]]) -> Optional[str]:
    """Use exported Playwright storage when no persistent user_data_dir profile is active."""
    if not browser_session:
        return None
    if browser_session.get("auth_ready") is False:
        return None
    if has_browser_session(browser_session):
        return None
    raw = str(browser_session.get("storage_state_path") or "").strip()
    if not raw:
        return None
    p = Path(raw)
    return str(p.resolve()) if p.is_file() else None


def _playwright_cookie_attrs(raw_value: Any) -> tuple[str | None, Dict[str, Any]]:
    if not isinstance(raw_value, dict):
        return (str(raw_value), {}) if raw_value is not None else (None, {})

    value = raw_value.get("value")
    if value is None:
        return None, {}

    attrs: Dict[str, Any] = {}
    for key in ("expires", "httpOnly", "path", "secure", "sameSite"):
        if key in raw_value and raw_value[key] is not None:
            attrs[key] = raw_value[key]
    return str(value), attrs


def _cookie_payload_for_domain(name: str, value: str, domain: str, attrs: Dict[str, Any]) -> Dict[str, Any]:
    item: Dict[str, Any] = {
        "name": name,
        "value": value,
        "domain": domain,
        "path": str(attrs.get("path") or "/"),
    }
    item.update({k: v for k, v in attrs.items() if k in {"expires", "httpOnly", "secure", "sameSite"}})
    if name.startswith("__Secure-"):
        item["secure"] = True
    return item


def _host_cookie_payload(name: str, value: str, host: str, attrs: Dict[str, Any]) -> Dict[str, Any]:
    item: Dict[str, Any] = {
        "name": name,
        "value": value,
        "url": f"https://{host}/",
        "path": "/",
        "secure": True,
    }
    item.update({k: v for k, v in attrs.items() if k in {"expires", "httpOnly", "sameSite"}})
    return item


def cookie_items_for_hosts(hosts: set[str], cookies: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build Playwright cookie payloads for all candidate hosts."""
    cookie_items: List[Dict[str, Any]] = []
    for host in hosts:
        for name, value in cookies.items():
            name = str(name or "")
            cookie_value, attrs = _playwright_cookie_attrs(value)
            if not name or cookie_value is None:
                continue
            if name.startswith("__Host-"):
                cookie_items.append(_host_cookie_payload(name, cookie_value, host, attrs))
                continue
            for domain in cookie_domains_for_host(host):
                cookie_items.append(_cookie_payload_for_domain(name, cookie_value, domain, attrs))
    return cookie_items


def build_runtime_cookie_list(source_url: str, cookies: Dict[str, Any]) -> List[Dict[str, Any]]:
    host = (urlparse(source_url).hostname or "").lower()
    return cookie_items_for_hosts({host} if host else set(), cookies)
