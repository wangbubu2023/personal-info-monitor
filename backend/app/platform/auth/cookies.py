"""Best-effort cookie validity probing.

This module performs a single GET against a target site to determine whether a
cookie jar still allows authenticated access. It is intentionally generic —
the caller supplies the URL and a ``dict[str, str]`` cookie mapping — and may
be invoked from any layer (fetch collectors, ingest validators, etc.).
"""

from __future__ import annotations

import aiohttp
from yarl import URL

from app.utils.http import permissive_session_kwargs
from app.utils.logger import get_logger

logger = get_logger(__name__)


def domain_match(cookie_domain: str, target_host: str) -> bool:
    """Return ``True`` when ``cookie_domain`` plausibly covers ``target_host``.

    Mirrors the loose cookie-domain matching used during login capture: leading
    dots are stripped, both sides are lowercased, and either side may be the
    suffix of the other (eTLD+1 fallback).
    """

    domain = (cookie_domain or "").lstrip(".").lower()
    host = (target_host or "").lower()
    if not domain or not host:
        return False
    return host == domain or host.endswith("." + domain) or domain.endswith("." + host)


async def cookies_appear_valid(site_url: str, cookies: dict) -> bool:
    """Return ``True`` when ``cookies`` still grant authenticated access to ``site_url``.

    The check is conservative: any error or HTTP exception returns ``True`` so
    that we do not block fetch on a flaky precheck. Returning ``False`` requires
    a definitive signal (401/403, login-redirect URL fragment, or a login/
    captcha marker in the first 5KB of the body).
    """

    if not site_url or not isinstance(cookies, dict) or not cookies:
        return False

    markers = (
        "sign in",
        "log in",
        "subscribe",
        "create account",
        "verify you are human",
        "captcha",
        "access denied",
    )
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        cookie_jar = aiohttp.CookieJar()
        url_obj = URL(site_url)
        for name, value in cookies.items():
            key = str(name or "").strip()
            if not key or value is None:
                continue
            cookie_jar.update_cookies({key: str(value)}, response_url=url_obj)

        async with aiohttp.ClientSession(
            **permissive_session_kwargs(timeout=timeout, cookie_jar=cookie_jar)
        ) as session:
            async with session.get(
                site_url,
                allow_redirects=True,
            ) as response:
                if response.status in {401, 403}:
                    return False
                final_url = str(response.url).lower()
                if any(token in final_url for token in ("/login", "/signin", "/sign-in", "/subscribe", "captcha")):
                    return False
                body = (await response.text(errors="ignore"))[:5000].lower()
                if any(marker in body for marker in markers):
                    return False
                return True
    except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
        logger.debug("Skip cookie precheck for %s: %s", site_url, exc)
        return True
