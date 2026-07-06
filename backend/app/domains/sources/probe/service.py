"""Source probe service — detect the best fetch strategy and reachability.

Probe strategies are now plain classes registered in
:mod:`app.domains.sources.probe.strategies.registry`. ``ProbeService`` no longer
inherits from them; instead it instantiates them with a shared helpers
object (``self``). Existing ``_probe_*`` / ``_extract_*`` helpers are kept
as thin delegators so existing callers and tests continue to work.
"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from typing import Any, Dict, Optional
from urllib.parse import urljoin

import aiohttp
from yarl import URL as YarlURL

from app.config import get_settings
from app.domains.sources.probe.strategies.registry import STRATEGY_REGISTRY
from app.domains.sources.probe.strategies.result import ProbeResult
from app.domains.sources.probe.strategies.rss import (  # re-exported for callers
    KNOWN_RSS_FEEDS,
    _UNFETCHABLE,
    _USE_SCRAPING,
)
from app.platform.security.ssrf import _is_private_address, assert_public_http_target
from app.utils.http import permissive_session_kwargs
from app.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

# Per-task cookies applied to every probe HTTP request during a single probe() call.
# Uses ContextVar so concurrent probes (e.g. probe_all) don't leak cookies across tasks.
_probe_cookies_var: ContextVar[Optional[Dict[str, str]]] = ContextVar(
    "_probe_cookies", default=None
)

__all__ = [
    "ProbeService",
    "ProbeResult",
    "KNOWN_RSS_FEEDS",
    "_UNFETCHABLE",
    "_USE_SCRAPING",
]


class ProbeService:
    """Probe a URL to determine the best fetch strategy.

    Strategies are resolved through :data:`STRATEGY_REGISTRY`. Each strategy
    receives ``self`` as its helpers object and accesses shared HTTP / RSS
    utilities via the underscore-prefixed methods below.
    """

    TIMEOUT = aiohttp.ClientTimeout(total=15)
    MAX_REDIRECTS = 5
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    def __init__(self) -> None:
        self._strategies: Dict[str, Any] = {
            name: cls(self) for name, cls in STRATEGY_REGISTRY.items()
        }

    # ------------------------------------------------------------------
    # Dispatch.
    # ------------------------------------------------------------------

    async def probe(
        self,
        url: str,
        source_type: str = "website",
        *,
        cookies: Optional[Dict[str, str]] = None,
    ) -> ProbeResult:
        """Dispatch to the probe strategy registered for ``source_type``.

        When ``cookies`` is provided, they are attached to every HTTP request
        issued during this probe (scoped to the initial URL's host via an
        aiohttp ``CookieJar``). This lets paywalled sources (WSJ, NYT, …) be
        probed against the user's saved authentication instead of returning
        the public paywall shell.
        """
        probe_method = f"_probe_{source_type}"
        handler = getattr(self, probe_method, None)
        if handler is None:
            return ProbeResult(status="error", message=f"Unknown source type: {source_type}")
        if cookies:
            token = _probe_cookies_var.set(cookies)
            try:
                return await handler(url)
            finally:
                _probe_cookies_var.reset(token)
        return await handler(url)

    async def probe_all(self, sources: list) -> Dict[str, ProbeResult]:
        """Probe multiple sources concurrently."""
        tasks: Dict[str, Any] = {}
        for s in sources:
            url = s.get("url") or s.url
            stype = s.get("type") or (s.type.value if hasattr(s.type, "value") else s.type)
            sid = str(s.get("id") or s.id)
            tasks[sid] = self.probe(url, stype)

        results: Dict[str, ProbeResult] = {}
        gathered = await asyncio.gather(*tasks.values(), return_exceptions=True)
        for sid, result in zip(tasks.keys(), gathered):
            if isinstance(result, Exception):
                results[sid] = ProbeResult(status="error", message=str(result))
            else:
                results[sid] = result
        return results

    # ------------------------------------------------------------------
    # Per-type delegators (kept for backward compatibility).
    # ------------------------------------------------------------------

    async def _probe_website(self, url: str) -> ProbeResult:
        return await self._strategies["website"].probe(url)

    async def _probe_rss(self, url: str) -> ProbeResult:
        return await self._strategies["rss"].probe(url)

    async def _probe_x(self, url: str) -> ProbeResult:
        return await self._strategies["x"].probe(url)

    async def _probe_youtube(self, url: str) -> ProbeResult:
        return await self._strategies["youtube"].probe(url)

    async def _probe_podcast(self, url: str) -> ProbeResult:
        return await self._strategies["podcast"].probe(url)

    # ------------------------------------------------------------------
    # Shared helpers exposed to strategies.
    # ------------------------------------------------------------------

    @staticmethod
    def _is_private_address(value: str) -> bool:
        return _is_private_address(value)

    async def _assert_public_http_target(self, url: str) -> None:
        await assert_public_http_target(url)

    @staticmethod
    def _get_settings():
        return get_settings()

    def _check_known_feeds(self, url: str) -> Optional[str]:
        return self._strategies["rss"].check_known_feeds(url)

    async def _discover_rss(self, url: str) -> Optional[str]:
        return await self._strategies["rss"].discover_rss(url)

    async def _try_common_rss_paths(self, url: str) -> Optional[str]:
        return await self._strategies["rss"].try_common_rss_paths(url)

    async def _test_rss_feed(self, rss_url: str) -> ProbeResult:
        return await self._strategies["rss"].test_rss_feed(rss_url)

    async def _test_scrape(self, url: str) -> ProbeResult:
        return await self._strategies["website"].test_scrape(url)

    # Type-specific delegators used by tests directly.

    def _extract_x_username(self, url: str) -> Optional[str]:
        return self._strategies["x"].extract_username(url)

    def _extract_youtube_channel_id(self, url: str) -> Optional[str]:
        return self._strategies["youtube"].extract_channel_id(url)

    def _extract_youtube_playlist_id(self, url: str) -> Optional[str]:
        return self._strategies["youtube"].extract_playlist_id(url)

    def _extract_youtube_feed_username(self, url: str) -> Optional[str]:
        return self._strategies["youtube"].extract_feed_username(url)

    def _extract_youtube_channel_hint(self, url: str) -> Optional[str]:
        return self._strategies["youtube"].extract_channel_hint(url)

    def _youtube_channel_page_candidates(self, url: str) -> list:
        return self._strategies["youtube"].channel_page_candidates(url)

    def _normalize_youtube_channel_page_url(self, url: str) -> str:
        return self._strategies["youtube"].normalize_channel_page_url(url)

    async def _resolve_youtube_channel_id_from_page(self, url: str) -> Optional[str]:
        return await self._strategies["youtube"].resolve_channel_id_from_page(url)

    async def _resolve_youtube_channel_id_from_search(self, hint: str) -> Optional[str]:
        return await self._strategies["youtube"].resolve_channel_id_from_search(hint)

    async def _extract_apple_podcast_rss(self, url: str) -> Optional[str]:
        return await self._strategies["podcast"].extract_apple_podcast_rss(url)

    # ------------------------------------------------------------------
    # HTTP helper (shared with every strategy).
    # ------------------------------------------------------------------

    @staticmethod
    def _build_cookie_jar(scope_url: str) -> Optional[aiohttp.CookieJar]:
        """Create a cookie jar seeded with the current ContextVar cookies.

        Cookies are scoped to the initial request URL's host (via
        ``response_url=YarlURL(scope_url)``), so redirects to unrelated hosts
        won't leak them. Returns ``None`` when no cookies are active — keeping
        the default aiohttp behaviour for unauthenticated probes.
        """
        cookies = _probe_cookies_var.get()
        if not cookies:
            return None
        try:
            scope = YarlURL(scope_url)
        except Exception as exc:  # noqa: BLE001 - yarl raises varied exceptions on malformed URLs
            logger.debug("Probe cookie jar skipped (invalid URL %s): %s", scope_url, exc)
            return None
        jar = aiohttp.CookieJar()
        for name, value in cookies.items():
            key = str(name or "").strip()
            if not key or value is None:
                continue
            try:
                jar.update_cookies({key: str(value)}, response_url=scope)
            except Exception as exc:  # noqa: BLE001 - defensive: bad cookie shouldn't kill probe
                logger.debug("Failed to attach probe cookie %s: %s", key, exc)
        return jar

    async def _http_get(self, url: str, timeout: int = 15) -> Optional[str]:
        try:
            ssl_option = False if settings.probe_disable_ssl_verify and settings.debug else None
            cookie_jar = self._build_cookie_jar(url)
            session_kwargs: Dict[str, Any] = {}
            if cookie_jar is not None:
                session_kwargs["cookie_jar"] = cookie_jar
            async with aiohttp.ClientSession(
                **permissive_session_kwargs(**session_kwargs)
            ) as session:
                current_url = url
                for _ in range(self.MAX_REDIRECTS + 1):
                    await self._assert_public_http_target(current_url)
                    async with session.get(
                        current_url,
                        headers=self.HEADERS,
                        timeout=aiohttp.ClientTimeout(total=timeout),
                        allow_redirects=False,
                        ssl=ssl_option,
                    ) as resp:
                        if resp.status in {301, 302, 303, 307, 308}:
                            location = (resp.headers.get("Location") or "").strip()
                            if not location:
                                return None
                            current_url = urljoin(str(resp.url), location)
                            continue
                        if resp.status != 200:
                            return None
                        return await resp.text()
                logger.warning("Probe request exceeded redirect limit: %s", url)
                return None
        except ValueError as exc:
            logger.warning("Blocked outbound probe request %s: %s", url, exc)
            return None
        except Exception as exc:  # noqa: BLE001 - aiohttp surfaces varied network errors
            logger.warning("HTTP GET failed for %s: %s", url, exc)
            return None
