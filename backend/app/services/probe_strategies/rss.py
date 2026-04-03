"""RSS probe strategy mixin."""

import re
from typing import Optional
from urllib.parse import urljoin

import feedparser
from bs4 import BeautifulSoup

from app.utils.logger import get_logger
from app.utils.url import host_matches, normalize_host
from app.services.probe_strategies.result import ProbeResult

logger = get_logger(__name__)

# Special sentinel values
_UNFETCHABLE = "__UNFETCHABLE__"  # Platform cannot be scraped at all
_USE_SCRAPING = "__SCRAPING__"    # No RSS, but scraping should work

# Known RSS feed URLs for popular sites that hide their feeds
from typing import Dict
KNOWN_RSS_FEEDS: Dict[str, Optional[str]] = {
    "bloomberg.com": "https://feeds.bloomberg.com/markets/news.rss",
    "cnbc.com": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
    "reuters.com": _USE_SCRAPING,  # Old RSS URL deprecated, site needs scraping
    "businessinsider.com": "https://feeds.businessinsider.com/custom/all",
    "wsj.com": "https://feeds.a.dj.com/rss/RSSWorldNews.xml",
    "morningbrew.com": _USE_SCRAPING,  # Cloudflare protected, needs JS or scraping
    "a16z.com": _USE_SCRAPING,  # /feed/ returns 404, site is SPA
    "hai.stanford.edu": "https://hai.stanford.edu/news/feed",
    "theinformation.com": _UNFETCHABLE,  # Paywall, feed returns 403
    "caixin.com": _USE_SCRAPING,  # RSSHub unreliable
    "21jingji.com": _USE_SCRAPING,  # No RSS, use scraping
    "facebook.com": _UNFETCHABLE,  # Not scrapable
}


class RssProbeStrategy:

    async def _probe_rss(self, url: str):
        """Probe a direct RSS/Atom feed URL."""
        result = await self._test_rss_feed(url)
        if result.status == "ok":
            return result

        return ProbeResult(
            status="error",
            strategy="rss",
            rss_url=url,
            message=getattr(result, "message", "") or "RSS feed 不可用",
        )

    def _check_known_feeds(self, url: str) -> Optional[str]:
        """Check if URL matches a known site with a hardcoded RSS feed.
        Returns:
            - feed URL string if known RSS exists
            - _UNFETCHABLE if the site cannot be fetched at all
            - _USE_SCRAPING if the site has no RSS but can be scraped
            - None if unknown (not in the dict)
        """
        target_host = normalize_host(url)
        for domain, feed_url in KNOWN_RSS_FEEDS.items():
            if host_matches(target_host, normalize_host(domain)):
                return feed_url  # may be a URL, _UNFETCHABLE, or _USE_SCRAPING
        return None

    async def _discover_rss(self, url: str) -> Optional[str]:
        """Discover RSS feed from HTML <link> tags."""
        try:
            html = await self._http_get(url)
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
        except Exception as e:
            logger.warning(f"RSS discovery failed for {url}: {e}")
        return None

    async def _try_common_rss_paths(self, url: str) -> Optional[str]:
        """Try common RSS feed URL patterns."""
        common = [
            "/feed", "/feed/", "/rss", "/rss/", "/rss.xml",
            "/feed.xml", "/atom.xml", "/index.xml",
            "/feeds/posts/default", "/blog/feed",
        ]
        for path in common:
            feed_url = urljoin(url.rstrip("/") + "/", path.lstrip("/"))
            try:
                text = await self._http_get(feed_url, timeout=8)
                if text and ("<rss" in text[:500] or "<feed" in text[:500] or "<atom" in text[:500]):
                    return feed_url
            except Exception as exc:
                logger.debug("RSS path probe failed for %s: %s", feed_url, exc)
                continue
        return None

    async def _test_rss_feed(self, rss_url: str):
        """Test if an RSS feed URL returns valid entries."""
        try:
            text = await self._http_get(rss_url)
            if not text:
                return ProbeResult(status="warning", strategy="rss", rss_url=rss_url,
                                   message=f"RSS URL 可达但返回为空: {rss_url}")

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
            elif feed.bozo:
                return ProbeResult(
                    status="warning", strategy="rss", rss_url=rss_url,
                    message=f"RSS 解析有问题: {feed.bozo_exception}",
                )
            else:
                return ProbeResult(
                    status="warning", strategy="rss", rss_url=rss_url,
                    message="RSS feed 为空（无条目）",
                )
        except Exception as e:
            return ProbeResult(status="error", message=f"RSS 测试失败: {e}")
