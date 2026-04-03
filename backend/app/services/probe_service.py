"""Source probe service — detect the best fetch strategy and reachability."""

import asyncio
import re
from typing import Any, Dict, Optional
from urllib.parse import urljoin

import aiohttp

from app.config import get_settings
from app.utils.logger import get_logger
from app.utils.ssrf import assert_public_http_target, _is_private_address

from app.services.probe_strategies.result import ProbeResult
from app.services.probe_strategies.rss import (
    RssProbeStrategy,
    KNOWN_RSS_FEEDS,
    _UNFETCHABLE,
    _USE_SCRAPING,
)
from app.services.probe_strategies.website import WebsiteProbeStrategy
from app.services.probe_strategies.x import XProbeStrategy
from app.services.probe_strategies.youtube import YouTubeProbeStrategy

logger = get_logger(__name__)
settings = get_settings()


class ProbeService(RssProbeStrategy, WebsiteProbeStrategy, XProbeStrategy, YouTubeProbeStrategy):
    """Probe a URL to determine the best fetch strategy."""

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

    @staticmethod
    def _is_private_address(value: str) -> bool:
        return _is_private_address(value)

    async def _assert_public_http_target(self, url: str) -> None:
        await assert_public_http_target(url)

    async def probe(self, url: str, source_type: str = "website") -> ProbeResult:
        """
        Probe a URL and determine the best fetch strategy.

        Returns a ProbeResult with status (ok/warning/error) and recommended strategy.
        """
        if source_type == "website":
            return await self._probe_website(url)
        elif source_type == "rss":
            return await self._probe_rss(url)
        elif source_type == "x":
            return await self._probe_x(url)
        elif source_type == "youtube":
            return await self._probe_youtube(url)
        elif source_type == "podcast":
            return await self._probe_podcast(url)
        else:
            return ProbeResult(status="error", message=f"Unknown source type: {source_type}")

    # ==================================================================
    #  Podcast probe
    # ==================================================================

    async def _probe_podcast(self, url: str) -> ProbeResult:
        """Probe a podcast URL."""
        # If it's a Spotify URL, we can't directly get RSS
        if "spotify.com" in url:
            return ProbeResult(
                status="error", strategy="none",
                message="Spotify 链接无法直接抓取。请替换为播客的真实 RSS feed URL（可在 podcast index 或 listennotes.com 查找）",
            )

        if "apple.com/podcast" in url or "podcasts.apple.com" in url:
            # Try to extract RSS from Apple Podcasts page
            rss_url = await self._extract_apple_podcast_rss(url)
            if rss_url:
                result = await self._test_rss_feed(rss_url)
                if result.status == "ok":
                    return result
            return ProbeResult(
                status="warning", strategy="none",
                message="Apple Podcasts 链接，尝试提取 RSS 失败。请替换为真实 RSS feed URL",
            )

        # Assume it's a direct RSS feed URL
        result = await self._test_rss_feed(url)
        if result.status == "ok":
            return result

        return ProbeResult(
            status="error", strategy="none",
            message=f"无法解析播客 feed：{url}",
        )

    async def _extract_apple_podcast_rss(self, url: str) -> Optional[str]:
        """Try to find RSS feed from Apple Podcasts."""
        try:
            # Apple Podcasts API: extract ID and look up
            match = re.search(r"id(\d+)", url)
            if not match:
                return None
            podcast_id = match.group(1)
            api_url = f"https://itunes.apple.com/lookup?id={podcast_id}&entity=podcast"
            text = await self._http_get(api_url)
            if text:
                import json
                data = json.loads(text)
                if data.get("results"):
                    return data["results"][0].get("feedUrl")
        except Exception as e:
            logger.warning(f"Apple Podcasts RSS extraction failed: {e}")
        return None

    # ==================================================================
    #  Batch probe
    # ==================================================================

    async def probe_all(self, sources: list) -> Dict[str, ProbeResult]:
        """Probe multiple sources concurrently."""
        tasks = {}
        for s in sources:
            url = s.get("url") or s.url
            stype = s.get("type") or (s.type.value if hasattr(s.type, 'value') else s.type)
            sid = str(s.get("id") or s.id)
            tasks[sid] = self.probe(url, stype)

        results = {}
        gathered = await asyncio.gather(*tasks.values(), return_exceptions=True)
        for sid, result in zip(tasks.keys(), gathered):
            if isinstance(result, Exception):
                results[sid] = ProbeResult(status="error", message=str(result))
            else:
                results[sid] = result
        return results

    # ==================================================================
    #  HTTP helper
    # ==================================================================

    async def _http_get(self, url: str, timeout: int = 15) -> Optional[str]:
        try:
            ssl_option = False if settings.probe_disable_ssl_verify else None
            async with aiohttp.ClientSession() as session:
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
        except Exception as exc:
            logger.warning("HTTP GET failed for %s: %s", url, exc)
            return None
