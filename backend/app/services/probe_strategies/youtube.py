"""YouTube probe strategy (standalone, no mixin)."""

from __future__ import annotations

import re
from typing import Any, List, Optional
from urllib.parse import parse_qs, urlparse

from app.services.probe_strategies.result import ProbeResult
from app.utils.logger import get_logger

logger = get_logger(__name__)


class YouTubeProbeStrategy:
    def __init__(self, helpers: Any):
        self.helpers = helpers

    async def probe(self, url: str) -> ProbeResult:
        playlist_id = self.extract_playlist_id(url)
        if playlist_id:
            feed_url = f"https://www.youtube.com/feeds/videos.xml?playlist_id={playlist_id}"
            result = await self.helpers._test_rss_feed(feed_url)
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

        channel_id = self.extract_channel_id(url)
        if not channel_id:
            channel_id = await self.resolve_channel_id_from_page(url)
        if not channel_id:
            hint = self.extract_channel_hint(url)
            if hint:
                channel_id = await self.resolve_channel_id_from_search(hint)
        if channel_id:
            feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
            result = await self.helpers._test_rss_feed(feed_url)
            if result.status == "ok":
                return ProbeResult(
                    status="ok",
                    strategy="rss",
                    rss_url=feed_url,
                    message=f"YouTube 频道 RSS 可用，包含 {result.sample_count} 条内容",
                    sample_count=result.sample_count,
                )

        username = self.extract_feed_username(url)
        if username:
            feed_url = f"https://www.youtube.com/feeds/videos.xml?user={username}"
            result = await self.helpers._test_rss_feed(feed_url)
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

    @staticmethod
    def extract_channel_id(url: str) -> Optional[str]:
        match = re.search(r"youtube\.com/channel/([a-zA-Z0-9_-]+)", url)
        if match:
            return match.group(1)
        return None

    async def resolve_channel_id_from_page(self, url: str) -> Optional[str]:
        for page_url in self.channel_page_candidates(url):
            html = await self.helpers._http_get(page_url, timeout=20)
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

    async def resolve_channel_id_from_search(self, hint: str) -> Optional[str]:
        if not hint:
            return None
        query = hint.strip().replace(" ", "+")
        search_url = f"https://www.youtube.com/results?search_query={query}&sp=EgIQAg%253D%253D"
        html = await self.helpers._http_get(search_url, timeout=20)
        if not html:
            return None
        m = re.search(r'"channelId":"(UC[a-zA-Z0-9_-]{22})"', html)
        if m:
            return m.group(1)
        return None

    @staticmethod
    def normalize_channel_page_url(url: str) -> str:
        if not url.startswith("http"):
            url = f"https://www.youtube.com/{url.lstrip('/')}"
        url = re.sub(r"/videos/?$", "", url)
        url = re.sub(r"/featured/?$", "", url)
        return url

    def channel_page_candidates(self, url: str) -> List[str]:
        normalized = self.normalize_channel_page_url(url)
        candidates = [normalized]
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

    @staticmethod
    def extract_playlist_id(url: str) -> Optional[str]:
        try:
            parsed = urlparse(url)
            if "youtube.com" in parsed.netloc:
                query = parse_qs(parsed.query)
                playlist_id = query.get("list", [None])[0]
                if playlist_id:
                    return playlist_id
        except ValueError as exc:
            logger.debug("YouTube playlist ID extraction failed for %s: %s", url, exc)
            return None
        return None

    @staticmethod
    def extract_feed_username(url: str) -> Optional[str]:
        match = re.search(r"youtube\.com/(?:c|user)/([a-zA-Z0-9_-]+)", url)
        if match:
            return match.group(1)
        return None

    @staticmethod
    def extract_channel_hint(url: str) -> Optional[str]:
        for pattern in [
            r"youtube\.com/@([a-zA-Z0-9_-]+)",
            r"youtube\.com/(?:c|user)/([a-zA-Z0-9_-]+)",
        ]:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None
