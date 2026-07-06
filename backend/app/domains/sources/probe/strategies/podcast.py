"""Podcast probe strategy (standalone)."""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from app.domains.sources.probe.strategies.result import ProbeResult
from app.utils.logger import get_logger

logger = get_logger(__name__)


class PodcastProbeStrategy:
    def __init__(self, helpers: Any):
        self.helpers = helpers

    async def probe(self, url: str) -> ProbeResult:
        if "spotify.com" in url:
            return ProbeResult(
                status="error", strategy="none",
                message=(
                    "Spotify 链接无法直接抓取。请替换为播客的真实 RSS feed URL"
                    "（可在 podcast index 或 listennotes.com 查找）"
                ),
            )

        if "apple.com/podcast" in url or "podcasts.apple.com" in url:
            rss_url = await self.helpers._extract_apple_podcast_rss(url)
            if rss_url:
                result = await self.helpers._test_rss_feed(rss_url)
                if result.status == "ok":
                    return result
            return ProbeResult(
                status="warning", strategy="none",
                message="Apple Podcasts 链接，尝试提取 RSS 失败。请替换为真实 RSS feed URL",
            )

        result = await self.helpers._test_rss_feed(url)
        if result.status == "ok":
            return result
        return ProbeResult(
            status="error", strategy="none",
            message=f"无法解析播客 feed：{url}",
        )

    async def extract_apple_podcast_rss(self, url: str) -> Optional[str]:
        try:
            match = re.search(r"id(\d+)", url)
            if not match:
                return None
            podcast_id = match.group(1)
            api_url = f"https://itunes.apple.com/lookup?id={podcast_id}&entity=podcast"
            text = await self.helpers._http_get(api_url)
            if text:
                data = json.loads(text)
                if data.get("results"):
                    return data["results"][0].get("feedUrl")
        except Exception as exc:  # noqa: BLE001 - iTunes API returns mixed error types
            logger.warning(f"Apple Podcasts RSS extraction failed: {exc}")
        return None
