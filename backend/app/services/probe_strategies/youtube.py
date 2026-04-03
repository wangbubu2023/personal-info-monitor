"""YouTube probe strategy mixin."""

import re
from typing import List, Optional
from urllib.parse import parse_qs, urlparse

from app.utils.logger import get_logger
from app.services.probe_strategies.result import ProbeResult

logger = get_logger(__name__)


class YouTubeProbeStrategy:

    async def _probe_youtube(self, url: str):
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
