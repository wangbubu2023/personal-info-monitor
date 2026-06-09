"""YouTube content collector using yt-dlp (no API key required)."""

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.domains.fetch.collectors.base import BaseCollector
from app.models import Source


class YouTubeCollector(BaseCollector):
    """Collector for YouTube channels and playlists using yt-dlp.
    
    yt-dlp handles YouTube's anti-bot measures without requiring an API key.
    We only extract metadata (title, description, upload_date) — no video
    is downloaded.
    """

    # Max number of recent videos to fetch per source.
    DEFAULT_VIDEO_COUNT = 3

    def __init__(self):
        super().__init__()

    def _build_ydl_opts(self, count: int) -> Dict:
        """Standard yt-dlp options for metadata-only extraction."""
        return {
            "quiet": True,
            "no_warnings": True,
            # extract_flat=True returns stubs only (no expensive extra calls).
            # We'll do a second pass for description if needed.
            "extract_flat": "in_playlist",
            "playlistend": count,
            # Avoid writing cookies / config files inside the container.
            "cookiefile": None,
            "no_color": True,
        }

    async def fetch(self, source: Source) -> List[Dict[str, Any]]:
        """Fetch the N most recent videos from a YouTube channel or playlist."""
        await self._check_ssrf(source.url)
        self.logger.info(f"Fetching YouTube source: {source.url}")
        try:
            import yt_dlp
        except ImportError:
            self.logger.error("yt-dlp is not installed. Please add yt-dlp to requirements.txt")
            return []

        metadata = source.metadata_ or {}
        video_count = int(metadata.get("video_count", self.DEFAULT_VIDEO_COUNT))

        # Normalise the URL to the /videos tab so yt-dlp lists uploads.
        url = self._normalise_channel_url(source.url)

        ydl_opts = self._build_ydl_opts(video_count)
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await asyncio.to_thread(ydl.extract_info, url, download=False)

            if not info:
                self.logger.warning(f"yt-dlp returned no info for: {url}")
                return []

            entries = info.get("entries") or []
            if not entries:
                # Single video URL (not a channel/playlist)
                entries = [info]

            results: List[Dict[str, Any]] = []
            for entry in entries:
                if not entry:
                    continue
                content = self._format_entry(entry, info)
                if self.validate_content(content):
                    results.append(content)

            self.logger.info(f"yt-dlp fetched {len(results)} videos from {source.url}")
            return results

        except Exception as exc:
            self.logger.error(f"yt-dlp failed for {source.url}: {exc}")
            return []

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _normalise_channel_url(self, url: str) -> str:
        """Ensure the URL ends at the channel root (strip /featured etc.)."""
        import re
        url = url.rstrip("/")
        url = re.sub(r"/(videos|featured|about|community|shorts)$", "", url)
        return url

    def _parse_upload_date(self, upload_date: Optional[str]) -> Optional[datetime]:
        """Parse yt-dlp's YYYYMMDD upload_date string into a naive UTC datetime."""
        if not upload_date:
            return None
        try:
            return datetime.strptime(upload_date, "%Y%m%d")
        except Exception as exc:
            self.logger.debug("Failed to parse upload_date '%s': %s", upload_date, exc)
            return None

    def _format_entry(self, entry: Dict, parent_info: Dict) -> Dict[str, Any]:
        """Convert a yt-dlp entry dict into the standard content format."""
        video_id = entry.get("id") or entry.get("display_id") or ""
        title = (entry.get("title") or "").strip()
        description = (entry.get("description") or entry.get("summary") or "").strip()
        upload_date_str = entry.get("upload_date")
        publish_time = self._parse_upload_date(upload_date_str)

        channel = (
            entry.get("channel")
            or entry.get("uploader")
            or parent_info.get("channel")
            or parent_info.get("uploader")
            or parent_info.get("title")
            or "YouTube"
        )

        # Thumbnail: yt-dlp returns a list sorted best-first.
        thumbnail: Optional[str] = None
        thumbnails = entry.get("thumbnails") or []
        if thumbnails:
            thumbnail = thumbnails[-1].get("url")  # highest quality is last

        watch_url = (
            entry.get("url")
            or entry.get("webpage_url")
            or (f"https://www.youtube.com/watch?v={video_id}" if video_id else "")
        )

        return {
            "external_id": video_id or watch_url or title,
            "title": title or f"YouTube video {video_id}",
            # content = description, which is what the user asked for.
            "content": description,
            "url": watch_url,
            "publish_time": publish_time,
            "metadata": {
                "channel": channel,
                "video_id": video_id,
                "thumbnail": thumbnail,
                "source_strategy": "yt_dlp",
            },
        }
