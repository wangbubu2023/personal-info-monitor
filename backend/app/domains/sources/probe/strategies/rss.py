"""RSS probe strategy.

Converted from a mixin into a plain class that holds a reference to a
helpers object exposing shared HTTP + feed utilities. See
``base.py`` for the expected helpers interface.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional
from urllib.parse import urljoin

import feedparser
from bs4 import BeautifulSoup

from app.domains.sources.probe.strategies.result import ProbeResult
from app.utils.logger import get_logger
from app.utils.url import host_matches, normalize_host

logger = get_logger(__name__)

_UNFETCHABLE = "__UNFETCHABLE__"
_USE_SCRAPING = "__SCRAPING__"

KNOWN_RSS_FEEDS: Dict[str, Optional[str]] = {
    "bloomberg.com": "https://feeds.bloomberg.com/markets/news.rss",
    "cnbc.com": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
    "reuters.com": _USE_SCRAPING,
    "businessinsider.com": "https://feeds.businessinsider.com/custom/all",
    "wsj.com": "https://feeds.a.dj.com/rss/RSSWorldNews.xml",
    "morningbrew.com": _USE_SCRAPING,
    "a16z.com": _USE_SCRAPING,
    "hai.stanford.edu": "https://hai.stanford.edu/news/feed",
    "theinformation.com": _UNFETCHABLE,
    "caixin.com": _USE_SCRAPING,
    "21jingji.com": _USE_SCRAPING,
    "facebook.com": _UNFETCHABLE,
}


class RssProbeStrategy:
    """Probe a direct RSS / Atom feed URL."""

    def __init__(self, helpers: Any):
        self.helpers = helpers

    async def probe(self, url: str) -> ProbeResult:
        result = await self.helpers._test_rss_feed(url)
        if result.status == "ok":
            return result
        return ProbeResult(
            status="error",
            strategy="rss",
            rss_url=url,
            message=getattr(result, "message", "") or "RSS feed 不可用",
        )

    # ------------------------------------------------------------------
    # Helper methods used by multiple strategies (RSS/website/YouTube).
    # ------------------------------------------------------------------

    def check_known_feeds(self, url: str) -> Optional[str]:
        target_host = normalize_host(url)
        for domain, feed_url in KNOWN_RSS_FEEDS.items():
            if host_matches(target_host, normalize_host(domain)):
                return feed_url
        return None

    async def discover_rss(self, url: str) -> Optional[str]:
        try:
            html = await self.helpers._http_get(url)
            if not html:
                return None
            soup = BeautifulSoup(html, "html.parser")
            feed_links = soup.find_all("link", type=re.compile(r"(rss|atom|feed)"))
            if feed_links:
                href = feed_links[0].get("href")
                if href:
                    if href.startswith("/"):
                        href = urljoin(url, href)
                    return href
        except (ValueError, OSError) as exc:
            logger.warning(f"RSS discovery failed for {url}: {exc}")
        return None

    async def try_common_rss_paths(self, url: str) -> Optional[str]:
        common = [
            "/feed", "/feed/", "/rss", "/rss/", "/rss.xml",
            "/feed.xml", "/atom.xml", "/index.xml",
            "/feeds/posts/default", "/blog/feed",
        ]
        for path in common:
            feed_url = urljoin(url.rstrip("/") + "/", path.lstrip("/"))
            try:
                text = await self.helpers._http_get(feed_url, timeout=8)
                if text and ("<rss" in text[:500] or "<feed" in text[:500] or "<atom" in text[:500]):
                    return feed_url
            except (ValueError, OSError) as exc:
                logger.debug("RSS path probe failed for %s: %s", feed_url, exc)
                continue
        return None

    async def test_rss_feed(self, rss_url: str) -> ProbeResult:
        try:
            text = await self.helpers._http_get(rss_url)
            if not text:
                return ProbeResult(
                    status="warning", strategy="rss", rss_url=rss_url,
                    message=f"RSS URL 可达但返回为空: {rss_url}",
                )
            feed = feedparser.parse(text)
            count = len(feed.entries)
            if count > 0:
                return ProbeResult(
                    status="ok",
                    strategy="rss",
                    rss_url=rss_url,
                    message=f"RSS feed 可用，包含 {count} 条内容",
                    sample_count=count,
                )
            if feed.bozo:
                return ProbeResult(
                    status="warning", strategy="rss", rss_url=rss_url,
                    message=f"RSS 解析有问题: {feed.bozo_exception}",
                )
            return ProbeResult(
                status="warning", strategy="rss", rss_url=rss_url,
                message="RSS feed 为空（无条目）",
            )
        except Exception as exc:  # noqa: BLE001 - feedparser raises a variety of types
            return ProbeResult(status="error", message=f"RSS 测试失败: {exc}")
