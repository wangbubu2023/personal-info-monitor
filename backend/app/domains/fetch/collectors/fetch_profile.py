"""Website fetch profiles and diagnostics.

Profiles here are intentionally conservative. They record known extraction
and failure characteristics for difficult publishers, but they do not spoof
crawlers, clear cookies, block subscription scripts, or use archive mirrors.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any
from urllib.parse import urlparse


_SITE_PROFILES: dict[str, dict[str, Any]] = {
    "reuters.com": {
        "structured_first": True,
        "known_paywall_vendors": ["arcxp"],
        "diagnostic_note": "Reuters pages may expose article text before Arc XP subscription scripts run.",
    },
    "bloomberg.com": {
        "structured_first": True,
        "known_paywall_vendors": ["bloomberg_fence"],
        "diagnostic_note": "Bloomberg often serves shell pages unless a valid user session is present.",
    },
    "wsj.com": {
        "structured_first": True,
        "known_paywall_vendors": ["cxense", "piano"],
        "diagnostic_note": "WSJ frequently needs RSS discovery or a user-provided browser session.",
    },
    "ft.com": {
        "structured_first": True,
        "known_paywall_vendors": ["piano"],
        "diagnostic_note": "FT should prefer structured extraction and configured RSS before browser hydration.",
    },
    "nytimes.com": {
        "structured_first": True,
        "known_paywall_vendors": ["nyt_meter"],
        "diagnostic_note": "NYTimes content quality depends heavily on article JSON and valid sessions.",
    },
    "washingtonpost.com": {
        "structured_first": True,
        "known_paywall_vendors": ["washingtonpost_tetro"],
        "diagnostic_note": "Washington Post pages can include client-side access gates in article assets.",
    },
    "economist.com": {
        "structured_first": True,
        "known_paywall_vendors": ["zephr"],
        "diagnostic_note": "Economist section feeds are often more reliable than HTML listing pages.",
    },
}

_VENDOR_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("piano", "Piano/TinyPass", re.compile(r"(piano\.io|tinypass\.com|api/tinypass)", re.I)),
    ("zephr", "Zephr", re.compile(r"(zephr\.com/zephr-browser|/zephr/feature)", re.I)),
    ("poool", "Poool", re.compile(r"poool\.fr/", re.I)),
    ("cxense", "Cxense", re.compile(r"cxense\.com/", re.I)),
    ("matheranalytics", "MatherAnalytics", re.compile(r"matheranalytics\.com/", re.I)),
    ("arcxp", "Arc XP subscriptions", re.compile(r"/arc/subs/p\.min\.js", re.I)),
    ("bloomberg_fence", "Bloomberg fence", re.compile(r"bwbx\.io/s3/fence/fortress-client", re.I)),
    ("nyt_meter", "NYTimes meter", re.compile(r"(nytimes\.com/(meter\.js|svc/onsite-messaging)|mwcm\.nyt\.com)", re.I)),
    ("washingtonpost_tetro", "Washington Post Tetro", re.compile(r"washingtonpost\.com/.+/tetro-client", re.I)),
    ("economist_wall", "Economist wall", re.compile(r"economist\.com/(latest/wall-ui|script)\.js", re.I)),
)


def _host_from_url(url: str) -> str:
    return (urlparse(url).hostname or "").lower().lstrip("www.")


def _profile_for_host(host: str) -> dict[str, Any]:
    for suffix, profile in _SITE_PROFILES.items():
        if host == suffix or host.endswith("." + suffix):
            return deepcopy(profile)
    return {}


def get_fetch_profile(source_or_url: Any) -> dict[str, Any]:
    """Resolve a conservative fetch profile from URL plus source metadata."""
    url = str(getattr(source_or_url, "url", source_or_url) or "")
    profile = _profile_for_host(_host_from_url(url))

    metadata = getattr(source_or_url, "metadata_", None)
    if isinstance(metadata, dict):
        override = metadata.get("fetch_profile")
        if isinstance(override, dict):
            merged = dict(profile)
            merged.update(override)
            profile = merged
    return profile


def detect_paywall_vendors(html: str, url: str = "") -> list[dict[str, str]]:
    """Detect known access-gate/vendor assets for diagnostics only."""
    haystack = f"{url}\n{html or ''}"
    seen: set[str] = set()
    vendors: list[dict[str, str]] = []
    for code, label, pattern in _VENDOR_PATTERNS:
        if code in seen:
            continue
        if pattern.search(haystack):
            seen.add(code)
            vendors.append({"code": code, "label": label})
    return vendors


def diagnose_article_html(html: str, url: str = "", profile: dict[str, Any] | None = None) -> dict[str, Any]:
    """Summarise fetch/extraction risks visible in a returned article page."""
    profile = profile if isinstance(profile, dict) else {}
    text = html or ""
    lower = text.lower()
    vendors = detect_paywall_vendors(text, url)
    shell_tokens = (
        "subscribe to continue",
        "sign in to continue",
        "login to continue",
        "register to continue",
        "already a subscriber",
        "enable javascript",
        "access denied",
        "captcha",
    )
    shell_like = len(text) < 8000 and any(token in lower for token in shell_tokens)
    diagnostics: dict[str, Any] = {}
    if vendors:
        diagnostics["paywall_vendors"] = vendors
    if shell_like:
        diagnostics["shell_like"] = True
    if profile.get("known_paywall_vendors"):
        diagnostics["profile_known_paywall_vendors"] = profile.get("known_paywall_vendors")
    if profile.get("diagnostic_note"):
        diagnostics["fetch_profile_note"] = profile.get("diagnostic_note")
    return diagnostics


__all__ = ["detect_paywall_vendors", "diagnose_article_html", "get_fetch_profile"]
