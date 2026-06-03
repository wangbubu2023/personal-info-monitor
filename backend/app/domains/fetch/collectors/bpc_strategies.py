"""Bypass Paywalls Clean (BPC) inspired strategies for Fetch Layer.

Provides utilities for spoofing User-Agent/Referer, rotating X-Forwarded-For IPs,
and blocking common SaaS paywall scripts via Playwright route interception.
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


def _clean_header_value(value: Any, *, max_len: int = 512) -> str:
    text = str(value or "").strip()
    if not text or len(text) > max_len:
        return ""
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        return ""
    return text


def generate_random_ip() -> str:
    """Generate a random plausible IP address for X-Forwarded-For."""
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
    combined_regex = re.compile("|".join(patterns), re.IGNORECASE)

    async def interceptor(route):
        request = route.request
        if combined_regex.search(request.url):
            await route.abort("blockedbyclient")
            return

        await route.continue_()

    return interceptor
