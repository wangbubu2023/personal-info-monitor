"""Source probe service — detect the best fetch strategy and reachability."""

import asyncio
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urljoin, urlparse

import aiohttp
import feedparser
from bs4 import BeautifulSoup

from app.config import get_settings
from app.utils.datetime import to_iso_z, utcnow_naive
from app.utils.logger import get_logger
from app.utils.ssrf import assert_public_http_target, _is_private_address
from app.utils.url import host_matches, normalize_host

logger = get_logger(__name__)
settings = get_settings()

# Special sentinel values
_UNFETCHABLE = "__UNFETCHABLE__"  # Platform cannot be scraped at all
_USE_SCRAPING = "__SCRAPING__"    # No RSS, but scraping should work

# Known RSS feed URLs for popular sites that hide their feeds
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

class ProbeResult:
    """Result of a source probe."""

    def __init__(
        self,
        status: str = "unknown",       # ok, warning, error, unknown
        strategy: str = "none",         # rss, scrape, js, rsshub, api, none
        rss_url: Optional[str] = None,
        message: str = "",
        sample_count: int = 0,
    ):
        self.status = status
        self.strategy = strategy
        self.rss_url = rss_url
        self.message = message
        self.sample_count = sample_count

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "strategy": self.strategy,
            "rss_url": self.rss_url,
            "message": self.message,
            "sample_count": self.sample_count,
            "probed_at": to_iso_z(utcnow_naive()),
        }


class ProbeService:
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
        if source_type in ("website", "rss"):
            return await self._probe_website(url)
        elif source_type == "x":
            return await self._probe_x(url)
        elif source_type == "youtube":
            return await self._probe_youtube(url)
        elif source_type == "podcast":
            return await self._probe_podcast(url)
        else:
            return ProbeResult(status="error", message=f"Unknown source type: {source_type}")

    # ==================================================================
    #  Website probe
    # ==================================================================

    async def _probe_website(self, url: str) -> ProbeResult:
        """Probe a website URL."""
        # 1. Check known RSS feeds first
        known = self._check_known_feeds(url)
        if known is not None:
            if known == _UNFETCHABLE:
                # Give site-specific messages
                if "facebook.com" in url:
                    msg = "Facebook 个人页面不支持 RSS 或网页抓取"
                elif "theinformation.com" in url:
                    msg = "The Information 为付费订阅站，Feed 需要认证，暂不支持免费抓取"
                else:
                    msg = "该平台不支持自动抓取"
                return ProbeResult(
                    status="error",
                    strategy="none",
                    message=msg,
                )
            if known == _USE_SCRAPING:
                # Skip RSS attempts, go directly to scraping
                scrape_result = await self._test_scrape(url)
                if scrape_result.sample_count > 0:
                    return scrape_result
                # If scraping also fails, continue to the normal flow
            else:
                # Test the known feed
                result = await self._test_rss_feed(known)
                if result.status == "ok":
                    return result

        # 2. Try to discover RSS feed from page
        rss_url = await self._discover_rss(url)
        if rss_url:
            result = await self._test_rss_feed(rss_url)
            if result.status == "ok":
                return result

        # 3. Try common RSS paths
        rss_url = await self._try_common_rss_paths(url)
        if rss_url:
            result = await self._test_rss_feed(rss_url)
            if result.status == "ok":
                return result

        # 4. Try static scraping
        scrape_result = await self._test_scrape(url)
        if scrape_result.status == "ok":
            return scrape_result

        # 5. Nothing worked
        return ProbeResult(
            status="error",
            strategy="none",
            message="无法通过 RSS 或网页抓取获取内容，可能需要 JS 渲染或该站有反爬保护",
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

    async def _test_rss_feed(self, rss_url: str) -> ProbeResult:
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

    async def _test_scrape(self, url: str) -> ProbeResult:
        """Test if we can scrape articles from the page."""
        try:
            html = await self._http_get(url)
            if not html:
                return ProbeResult(status="error", strategy="scrape",
                                   message="网页无法访问")

            soup = BeautifulSoup(html, "html.parser")
            # Try to find article-like elements (covers both English & Chinese sites)
            selectors = [
                "article", ".post", ".entry", "main article",
                "[class*='article']", "[class*='post']", "[class*='story']",
                "[class*='news']", "[class*='item']", "[class*='card']",
                ".list-item", ".feed-item", ".content-item",
                "li[class]>a[href]",  # common list-based layouts
            ]
            articles = []
            for sel in selectors:
                try:
                    articles = soup.select(sel)
                except Exception as exc:
                    logger.debug("BS4 select failed: %s", exc)
                    continue
                if len(articles) >= 3:
                    break

            if not articles:
                # Try finding links with titles
                links = soup.select("a[href]")
                article_links = [
                    a for a in links
                    if a.get_text(strip=True)
                    and len(a.get_text(strip=True)) > 20
                    and a.get("href", "").startswith(("http", "/"))
                ]
                if len(article_links) >= 3:
                    return ProbeResult(
                        status="warning",
                        strategy="scrape",
                        message=f"未找到标准文章结构，但发现 {len(article_links)} 个链接可供提取",
                        sample_count=len(article_links),
                    )
                return ProbeResult(
                    status="error", strategy="scrape",
                    message="网页可访问但未找到可提取的文章内容，可能需要 JS 渲染",
                )

            return ProbeResult(
                status="ok" if len(articles) >= 3 else "warning",
                strategy="scrape",
                message=f"网页抓取可用，发现 {len(articles)} 篇文章",
                sample_count=len(articles),
            )
        except Exception as e:
            return ProbeResult(status="error", strategy="scrape",
                               message=f"网页抓取测试失败: {e}")

    # ==================================================================
    #  X (Twitter) probe
    # ==================================================================

    async def _probe_x(self, url: str) -> ProbeResult:
        """Probe an X/Twitter URL."""
        username = self._extract_x_username(url)
        if not username:
            return ProbeResult(status="error", message=f"无法从 URL 中提取用户名: {url}")

        from app.config import get_settings
        settings = get_settings()

        # 1. 尝试 twikit GraphQL（最高优先级）
        auth_token = getattr(settings, "x_auth_token", None)
        ct0_token = getattr(settings, "x_ct0_token", None)
        if auth_token and ct0_token:
            try:
                from twikit import Client as TwikitClient
                client = TwikitClient("en-US")
                client.set_cookies({"auth_token": auth_token, "ct0": ct0_token})
                user = await client.get_user_by_screen_name(username)
                if user:
                    return ProbeResult(
                        status="ok", strategy="graphql",
                        message=f"GraphQL 可用，@{username} 已验证 (user_id={user.id})",
                        sample_count=0,
                    )
            except ImportError:
                logger.warning("twikit 未安装，跳过 GraphQL 探测")
            except Exception as e:
                logger.warning(f"GraphQL 探测 @{username} 失败: {e}")

        # 2. 尝试 RSSHub
        rsshub_url = getattr(settings, "rsshub_url", "https://rsshub.app")
        feed_url = f"{rsshub_url}/twitter/user/{username}"

        text = await self._http_get(feed_url, timeout=20)
        if text:
            feed = feedparser.parse(text)
            if feed.entries:
                return ProbeResult(
                    status="ok", strategy="rsshub", rss_url=feed_url,
                    message=f"RSSHub 可用，@{username} 有 {len(feed.entries)} 条推文",
                    sample_count=len(feed.entries),
                )

        # 3. 尝试 Nitter
        raw_nitter = getattr(settings, "nitter_instances", None) or ""
        if raw_nitter:
            nitter_instances = [u.strip().rstrip("/") for u in raw_nitter.split(",") if u.strip()]
        else:
            nitter_instances = [
                "https://nitter.privacydev.net",
                "https://nitter.poast.org",
                "https://nitter.woodland.cafe",
            ]
        for inst in nitter_instances:
            nitter_feed = f"{inst}/{username}/rss"
            text = await self._http_get(nitter_feed, timeout=10)
            if text:
                feed = feedparser.parse(text)
                if feed.entries:
                    return ProbeResult(
                        status="ok", strategy="nitter", rss_url=nitter_feed,
                        message=f"Nitter 可用，@{username} 有 {len(feed.entries)} 条推文",
                        sample_count=len(feed.entries),
                    )

        # 4. 检查 Bearer Token
        bearer = getattr(settings, "x_bearer_token", None)
        if bearer and bearer not in ("", "xxx"):
            return ProbeResult(
                status="warning", strategy="api",
                message=f"RSSHub/Nitter 均不可用，将使用官方 API（需 Bearer Token）",
            )

        # 5. 提示用户配置 Cookie
        if not (auth_token and ct0_token):
            return ProbeResult(
                status="error", strategy="none",
                message=f"@{username} 无法抓取：未配置 X_AUTH_TOKEN/X_CT0_TOKEN，且 RSSHub/Nitter 不可用",
            )

        return ProbeResult(
            status="error", strategy="none",
            message=f"@{username} 无法抓取：所有策略均失败",
        )

    def _extract_x_username(self, url: str) -> Optional[str]:
        if url.startswith("@"):
            return url[1:]
        match = re.search(r"(?:twitter\.com|x\.com)/(@)?([a-zA-Z0-9_]+)", url)
        if match:
            return match.group(2)
        if re.match(r"^[a-zA-Z0-9_]+$", url):
            return url
        return None

    # ==================================================================
    #  YouTube probe
    # ==================================================================

    async def _probe_youtube(self, url: str) -> ProbeResult:
        """Probe a YouTube URL."""
        playlist_id = self._extract_youtube_playlist_id(url)
        if playlist_id:
            feed_url = f"https://www.youtube.com/feeds/videos.xml?playlist_id={playlist_id}"
            result = await self._test_rss_feed(feed_url)
            if result.status == "ok":
                return ProbeResult(
                    status="ok",
                    strategy="rss",
                    rss_url=feed_url,
                    message=f"YouTube 播放列表 RSS 可用，包含 {result.sample_count} 条内容",
                    sample_count=result.sample_count,
                )
            return ProbeResult(
                status="error",
                strategy="none",
                message="YouTube 播放列表 RSS 不可用",
            )

        # Channel RSS path (no API key required)
        channel_id = self._extract_youtube_channel_id(url)
        if not channel_id:
            channel_id = await self._resolve_youtube_channel_id_from_page(url)
        if not channel_id:
            hint = self._extract_youtube_channel_hint(url)
            if hint:
                channel_id = await self._resolve_youtube_channel_id_from_search(hint)
        if channel_id:
            feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
            result = await self._test_rss_feed(feed_url)
            if result.status == "ok":
                return ProbeResult(
                    status="ok",
                    strategy="rss",
                    rss_url=feed_url,
                    message=f"YouTube 频道 RSS 可用，包含 {result.sample_count} 条内容",
                    sample_count=result.sample_count,
                )

        # Legacy /c/<name> or /user/<name> style feed
        username = self._extract_youtube_feed_username(url)
        if username:
            feed_url = f"https://www.youtube.com/feeds/videos.xml?user={username}"
            result = await self._test_rss_feed(feed_url)
            if result.status == "ok":
                return ProbeResult(
                    status="ok",
                    strategy="rss",
                    rss_url=feed_url,
                    message=f"YouTube 用户 RSS 可用，包含 {result.sample_count} 条内容",
                    sample_count=result.sample_count,
                )

        from app.config import get_settings
        settings = get_settings()
        api_key = settings.youtube_api_key
        if api_key and api_key not in ("xxx", ""):
            return ProbeResult(
                status="warning",
                strategy="api",
                message="RSS 不可用，将尝试 YouTube API 抓取",
            )

        return ProbeResult(
            status="error",
            strategy="none",
            message="YouTube RSS 不可用，且未配置有效 YOUTUBE_API_KEY",
        )

    def _extract_youtube_channel_id(self, url: str) -> Optional[str]:
        """Extract channel ID from YouTube URL if present."""
        match = re.search(r"youtube\.com/channel/([a-zA-Z0-9_-]+)", url)
        if match:
            return match.group(1)
        return None

    async def _resolve_youtube_channel_id_from_page(self, url: str) -> Optional[str]:
        """Resolve channel ID by parsing the public YouTube page."""
        for page_url in self._youtube_channel_page_candidates(url):
            html = await self._http_get(page_url, timeout=20)
            if not html:
                continue

            patterns = [
                r'"channelId":"(UC[a-zA-Z0-9_-]{22})"',
                r'"externalId":"(UC[a-zA-Z0-9_-]{22})"',
                r'itemprop="channelId"\s+content="(UC[a-zA-Z0-9_-]{22})"',
                r'channel_id=(UC[a-zA-Z0-9_-]{22})',
            ]
            for pattern in patterns:
                m = re.search(pattern, html)
                if m:
                    return m.group(1)
        return None

    async def _resolve_youtube_channel_id_from_search(self, hint: str) -> Optional[str]:
        """Resolve channel id from YouTube search results page."""
        if not hint:
            return None
        query = hint.strip().replace(" ", "+")
        search_url = f"https://www.youtube.com/results?search_query={query}&sp=EgIQAg%253D%253D"
        html = await self._http_get(search_url, timeout=20)
        if not html:
            return None
        m = re.search(r'"channelId":"(UC[a-zA-Z0-9_-]{22})"', html)
        if m:
            return m.group(1)
        return None

    def _normalize_youtube_channel_page_url(self, url: str) -> str:
        """Normalize channel-like URL for page parsing."""
        if not url.startswith("http"):
            url = f"https://www.youtube.com/{url.lstrip('/')}"
        url = re.sub(r"/videos/?$", "", url)
        url = re.sub(r"/featured/?$", "", url)
        return url

    def _youtube_channel_page_candidates(self, url: str) -> List[str]:
        """Build candidate URLs for channel-page probing."""
        normalized = self._normalize_youtube_channel_page_url(url)
        candidates = [normalized]

        # Legacy custom URLs like /c/<name> and /user/<name> may 404 now.
        match = re.search(r"youtube\.com/(?:c|user)/([a-zA-Z0-9_-]+)", normalized)
        if match:
            handle_url = f"https://www.youtube.com/@{match.group(1)}"
            candidates.append(handle_url)
            candidates.append(f"{handle_url}/videos")

        deduped: List[str] = []
        seen = set()
        for item in candidates:
            if item not in seen:
                seen.add(item)
                deduped.append(item)
        return deduped

    def _extract_youtube_playlist_id(self, url: str) -> Optional[str]:
        """Extract playlist ID from YouTube playlist URL."""
        try:
            parsed = urlparse(url)
            if "youtube.com" in parsed.netloc:
                query = parse_qs(parsed.query)
                playlist_id = query.get("list", [None])[0]
                if playlist_id:
                    return playlist_id
        except Exception as exc:
            logger.debug("YouTube playlist ID extraction failed for %s: %s", url, exc)
            return None
        return None

    def _extract_youtube_feed_username(self, url: str) -> Optional[str]:
        """Extract legacy user feed identifier from channel URL."""
        match = re.search(r"youtube\.com/(?:c|user)/([a-zA-Z0-9_-]+)", url)
        if match:
            return match.group(1)
        return None

    def _extract_youtube_channel_hint(self, url: str) -> Optional[str]:
        """Extract channel hint for search-based fallback."""
        for pattern in [
            r"youtube\.com/@([a-zA-Z0-9_-]+)",
            r"youtube\.com/(?:c|user)/([a-zA-Z0-9_-]+)",
        ]:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

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
