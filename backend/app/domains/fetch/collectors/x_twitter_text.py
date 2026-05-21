"""Pure text utilities for the X/Twitter collector.

Extracting these keeps :mod:`app.domains.fetch.collectors.x_twitter` focused on fetch
strategies. Nothing here depends on collector instance state.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

ARTICLE_URL_RE = re.compile(r"(?:https?://)?(?:x\.com|twitter\.com)/i/article/\d+", re.IGNORECASE)
_X_HOSTS = frozenset({"x.com", "twitter.com", "www.x.com", "www.twitter.com", "mobile.twitter.com"})
_X_INTERSTITIAL_MARKERS = (
    "javascript is disabled",
    "enable javascript",
    "switch to a supported browser",
    "supported browser",
    "help center",
    "x corp",
    "terms of service",
)


def extract_article_urls(text: str) -> List[str]:
    """Pull canonicalised ``https://x.com/i/article/...`` URLs out of free text."""
    if not text:
        return []
    seen: set[str] = set()
    urls: List[str] = []
    for match in ARTICLE_URL_RE.finditer(text):
        candidate = (match.group(0) or "").strip()
        if not candidate:
            continue
        if not candidate.startswith("http://") and not candidate.startswith("https://"):
            candidate = f"https://{candidate}"
        if candidate.startswith("http://"):
            candidate = "https://" + candidate[len("http://"):]
        if candidate in seen:
            continue
        seen.add(candidate)
        urls.append(candidate)
    return urls


def extract_tweet_id(value: str) -> Optional[str]:
    """Return the numeric tweet id embedded in ``value`` or ``None``."""
    if not value:
        return None
    if re.fullmatch(r"\d{6,32}", value):
        return value
    match = re.search(r"/status/(\d{6,32})", value)
    if match:
        return match.group(1)
    match = re.search(r"[:/](\d{6,32})(?:\D|$)", value)
    if match:
        return match.group(1)
    return None


def normalize_tweet_url(url: str, logger=None) -> str:
    """Rewrite Nitter-style permalinks to canonical ``x.com/<user>/status/<id>``."""
    try:
        parsed = urlparse(url)
        if "nitter" in parsed.netloc and "/status/" in parsed.path:
            parts = [p for p in parsed.path.split("/") if p]
            if len(parts) >= 3 and parts[1] == "status":
                return f"https://x.com/{parts[0]}/status/{parts[2]}"
    except ValueError as exc:
        if logger is not None:
            logger.debug("Failed to normalize tweet url '%s': %s", url, exc)
        return url
    return url


def title_looks_like_url(title: str) -> bool:
    if not title:
        return True
    title = title.strip().lower()
    return title.startswith("http://") or title.startswith("https://")


def build_title_from_text(text: str) -> str:
    """Derive a short title from an article body, skipping handles / stats noise."""
    if not text:
        return "X 长文"
    for raw in text.splitlines():
        first_line = (raw or "").strip()
        if not first_line or first_line.startswith("@"):
            continue
        if re.fullmatch(r"\d+(?:\.\d+)?(?:万|亿|k|K|m|M|千)?", first_line):
            continue
        if len(first_line) < 8:
            continue
        return first_line[:80] + ("..." if len(first_line) > 80 else "")
    fallback = text.strip()[:80]
    return fallback + ("..." if len(text.strip()) > 80 else "")


def clean_article_text(text: str) -> Optional[str]:
    """Strip nav/auth UI noise from scraped long-form X article text."""
    if not text:
        return None

    cleaned = re.sub(r"\r\n?", "\n", text).strip()
    if not cleaned:
        return None

    deny_markers = [
        "This page is not supported.",
        "Something went wrong. Try reloading.",
        "People on X are the first to know.",
        "New to X?",
    ]
    if any(marker in cleaned for marker in deny_markers):
        return None

    lines = [line.strip() for line in cleaned.split("\n") if line.strip()]
    if not lines:
        return None

    skip_exact = {
        "Log in",
        "Sign up",
        "Retry",
        "Posts",
        "Replies",
        "Highlights",
        "Articles",
        "Media",
        "Terms of Service",
        "Privacy Policy",
        "Cookie Policy",
        "Accessibility",
        "Ads info",
        "More",
        "查看键盘快捷键",
        "要查看键盘快捷键，按下问号",
        "键盘快捷键",
        "键盘快捷方式",
        "文章",
        "加入",
        "注册",
        "探索",
        "通知",
        "消息",
    }
    filtered: List[str] = []
    for line in lines:
        if line in skip_exact or line.startswith("@"):
            continue
        if re.fullmatch(r"[·•\-\s]+", line):
            continue
        if re.fullmatch(r"\d+(?:\.\d+)?(?:万|亿|k|K|m|M|千)?", line):
            continue
        if re.fullmatch(r"\d+\s*(?:秒|分钟|小时|天|周|月|年)", line):
            continue
        if re.fullmatch(r"\d+月\d+日", line):
            continue
        if line.startswith("© ") and "X Corp" in line:
            continue
        filtered.append(line)

    result = "\n".join(filtered).strip()
    return result if len(result) >= 280 else None


def build_x_cookie_items(cookies: Dict[str, str]) -> List[Dict[str, Any]]:
    """Expand a ``{name: value}`` cookie map into Playwright cookie payloads for x.com."""
    if not cookies:
        return []
    cookie_items: List[Dict[str, Any]] = []
    for name, value in cookies.items():
        if not name or value is None:
            continue
        for domain in ("x.com", ".x.com"):
            cookie_items.append(
                {
                    "name": str(name),
                    "value": str(value),
                    "domain": domain,
                    "path": "/",
                }
            )
    return cookie_items


def build_api_since_id(last_content_id: Optional[str]) -> Dict[str, Any]:
    tweet_id = extract_tweet_id(last_content_id or "")
    return {"since_id": tweet_id} if tweet_id else {}


def extract_username_from_url(url: str, metadata: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Resolve the X account handle from metadata override or URL pattern."""
    metadata = metadata or {}
    if "username" in metadata:
        return str(metadata["username"]).lstrip("@")

    if url.startswith("@"):
        return url[1:]

    match = re.search(r"(?:twitter\.com|x\.com)/(@)?([a-zA-Z0-9_]+)", url)
    if match:
        candidate = match.group(2)
        if candidate.lower() in {"home", "explore", "search", "i", "messages", "settings"}:
            return None
        return candidate
    if re.match(r"^[a-zA-Z0-9_]+$", url):
        return url
    return None


def is_x_status_page_url(url: str) -> bool:
    """True for tweet permalinks — plain HTTP+cookie fetch returns JS interstitial, not tweet text."""
    try:
        parsed = urlparse((url or "").strip())
        host = (parsed.hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        return host in _X_HOSTS and "/status/" in (parsed.path or "")
    except Exception:  # noqa: BLE001 - urlparse should not raise, stay defensive
        return False


def looks_like_x_interstitial_text(text: str) -> bool:
    """Detect X noscript / login-wall boilerplate mistaken for article body."""
    normalized = re.sub(r"\s+", " ", (text or "").strip().lower())
    if not normalized:
        return False
    hits = sum(1 for marker in _X_INTERSTITIAL_MARKERS if marker in normalized)
    if hits >= 3:
        return True
    return "javascript is disabled" in normalized and "x.com" in normalized
