"""Compatibility strategies used by the automatic website fetch fallback.

These are implementation details, not user preferences.  Normal requests must
always run first; a bounded compatibility profile is only tried after the
collector has positively observed an access/shell failure.
"""

import random
import re
from collections.abc import Callable
from typing import Any

# Standard BPC Spoofing Constants
GOOGLEBOT_UA = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
BINGBOT_UA = "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)"

GOOGLE_REFERER = "https://www.google.com/"
FACEBOOK_REFERER = "https://www.facebook.com/"
TWITTER_REFERER = "https://t.co/"

# Known SaaS paywall providers and common paywall scripts
BLOCKED_PAYWALL_DOMAINS_AND_PATTERNS = (
    r"tinypass\.com",
    r"piano\.io",
    r"poool\.fr",
    r"pelcro\.com",
    r"cxense\.com",
    r"qiota\.com",
    r"ampproject\.org/v0/amp-subscriptions-.*\.js",
    r"ampproject\.org/v0/amp-access-.*\.js",
    r"sophi\.io",
    r"blueconic\.net",
)

_AUTOMATIC_RETRY_REASONS = {
    "bot_wall",
    "dynamic_empty",
    "html_parse_empty",
    "http_403",
    "http_status_403",
    "shell_page",
}

_STRATEGY_KEYS = {
    "bpc_spoof_ua",
    "bpc_spoof_referer",
    "bpc_random_ip",
    "bpc_block_paywalls",
    "bpc_ephemeral_context",
}
_LEGACY_MANUAL_KEYS = _STRATEGY_KEYS | {"rss_only"}


def _clean_header_value(value: Any, *, max_len: int = 512) -> str:
    text = str(value or "").strip()
    if not text or len(text) > max_len:
        return ""
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        return ""
    return text


def generate_random_ip() -> str:
    """Generate a legacy X-Forwarded-For value.

    This does not change the network egress address.  It remains only for
    backwards compatibility with stored metadata and is intentionally absent
    from the automatic strategy profiles.
    """
    first_octet = random.choice(
        [octet for octet in range(1, 224) if octet not in {10, 127, 169, 172, 192}]
    )
    return f"{first_octet}.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}"


def get_spoofed_headers(metadata: dict[str, Any], default_ua: str) -> dict[str, str]:
    """Derive headers based on BPC strategies configured in metadata."""
    headers: dict[str, str] = {}

    # 1. User Agent Spoofing
    spoof_ua = metadata.get("bpc_spoof_ua")
    if spoof_ua == "googlebot":
        user_agent = GOOGLEBOT_UA
    elif spoof_ua == "bingbot":
        user_agent = BINGBOT_UA
    elif "bpc_custom_ua" in metadata:
        user_agent = _clean_header_value(metadata["bpc_custom_ua"])
    else:
        user_agent = default_ua
    headers["User-Agent"] = _clean_header_value(user_agent) or default_ua

    # 2. Referer Spoofing
    spoof_referer = metadata.get("bpc_spoof_referer")
    if spoof_referer == "google":
        headers["Referer"] = GOOGLE_REFERER
    elif spoof_referer == "facebook":
        headers["Referer"] = FACEBOOK_REFERER
    elif spoof_referer == "twitter":
        headers["Referer"] = TWITTER_REFERER
    elif "bpc_custom_referer" in metadata:
        referer = _clean_header_value(metadata["bpc_custom_referer"])
        if referer:
            headers["Referer"] = referer

    # 3. IP Spoofing (X-Forwarded-For)
    if metadata.get("bpc_random_ip"):
        headers["X-Forwarded-For"] = generate_random_ip()

    return headers


def automatic_retry_profiles(
    metadata: dict[str, Any] | None,
    *,
    has_authenticated_session: bool,
    reason: str | None,
) -> list[tuple[str, dict[str, Any]]]:
    """Return bounded, ordered fallback profiles for a diagnosed failure.

    Authenticated sessions retain their cookies and browser storage. Anonymous
    requests may additionally try a clean context. Rate limits, login errors,
    CAPTCHAs and network failures are deliberately excluded: changing headers
    does not fix them and can make the target site more suspicious.
    """

    base = dict(metadata) if isinstance(metadata, dict) else {}
    if base.get("fetch_strategy_mode", "auto") != "auto":
        return []
    if str(reason or "") not in _AUTOMATIC_RETRY_REASONS:
        return []

    # Old per-strategy switches must not silently leak into every attempt.
    # Custom block patterns remain available to the automatic interceptor.
    for key in _STRATEGY_KEYS:
        base.pop(key, None)

    if has_authenticated_session:
        variants = (
            ("search_referrer", {"bpc_spoof_referer": "google"}),
            ("subscription_script_block", {"bpc_block_paywalls": True}),
        )
    else:
        variants = (
            (
                "crawler_compatibility",
                {
                    "bpc_spoof_ua": "googlebot",
                    "bpc_spoof_referer": "google",
                },
            ),
            (
                "clean_browser_context",
                {
                    "bpc_spoof_ua": "googlebot",
                    "bpc_spoof_referer": "google",
                    "bpc_block_paywalls": True,
                    "bpc_ephemeral_context": True,
                },
            ),
        )
    return [(name, {**base, **overrides}) for name, overrides in variants]


def normalize_fetch_strategy_metadata(
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    """Migrate legacy user-facing switches to the automatic strategy mode.

    ``manual`` remains an internal compatibility escape hatch for tests and
    emergency operations, but the product UI no longer creates it.
    """

    normalized = dict(metadata) if isinstance(metadata, dict) else {}
    mode = str(normalized.get("fetch_strategy_mode") or "auto").strip().lower()
    if mode == "manual":
        return normalized
    if mode not in {"auto", "off"}:
        mode = "auto"
    for key in _LEGACY_MANUAL_KEYS:
        normalized.pop(key, None)
    normalized["fetch_strategy_mode"] = mode
    return normalized


def requires_bpc_playwright(metadata: dict[str, Any] | None) -> bool:
    """True when a configured strategy needs a browser context to have any effect."""
    m = metadata if isinstance(metadata, dict) else {}
    return bool(m.get("bpc_block_paywalls") or m.get("bpc_ephemeral_context"))


def get_bpc_playwright_interceptor(metadata: dict[str, Any]) -> Callable | None:
    """Return a Playwright route interceptor to block paywall scripts.

    Only blocks if 'bpc_block_paywalls' is enabled in metadata.
    Includes built-in SaaS domains, plus any 'bpc_custom_blocks' in metadata.
    """
    is_enabled = bool(metadata.get("bpc_block_paywalls", False))
    if not is_enabled:
        return None

    custom_blocks = metadata.get("bpc_custom_blocks", [])
    if not isinstance(custom_blocks, list):
        custom_blocks = []

    patterns = list(BLOCKED_PAYWALL_DOMAINS_AND_PATTERNS) + [
        re.escape(str(block)) for block in custom_blocks if _clean_header_value(block)
    ]
    if not patterns:
        return None
    combined_regex = re.compile("|".join(patterns), re.IGNORECASE)

    async def interceptor(route):
        request = route.request
        if combined_regex.search(request.url):
            await route.abort("blockedbyclient")
            return

        await route.continue_()

    return interceptor
