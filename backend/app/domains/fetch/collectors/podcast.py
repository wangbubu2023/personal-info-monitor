"""Podcast content collector."""

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.domains.fetch.collectors.base import BaseCollector
from app.domains.fetch.collectors.rss import RSSCollector
from app.models import Source


class PodcastCollector(BaseCollector):
    """Collector for podcast feeds."""
    
    def __init__(self):
        super().__init__()
        self.rss_collector = RSSCollector()
    
    async def fetch(self, source: Source) -> List[Dict[str, Any]]:
        """Fetch episodes from a podcast feed."""
        await self._check_ssrf(source.url)
        self.logger.info(f"Fetching podcast: {source.url}")
        
        # Podcasts are typically RSS feeds
        contents = await self.rss_collector.fetch(source)
        
        # Enhance with podcast-specific metadata
        enhanced_contents = []
        for content in contents:
            enhanced = self._enhance_podcast_content(content)
            enhanced_contents.append(enhanced)
        
        return enhanced_contents

    @staticmethod
    def _parse_duration_seconds(value: Any) -> Optional[int]:
        """Parse common podcast duration formats into seconds."""
        if value is None:
            return None
        if isinstance(value, (int, float)):
            seconds = int(value)
            return seconds if seconds >= 0 else None

        text = str(value).strip()
        if not text:
            return None
        if text.isdigit():
            return int(text)

        parts = text.split(":")
        if not 2 <= len(parts) <= 3:
            return None
        try:
            numbers = [int(part) for part in parts]
        except ValueError:
            return None
        if any(part < 0 for part in numbers):
            return None
        if len(numbers) == 2:
            minutes, seconds = numbers
            return minutes * 60 + seconds
        hours, minutes, seconds = numbers
        return hours * 3600 + minutes * 60 + seconds
    
    def _enhance_podcast_content(self, content: Dict[str, Any]) -> Dict[str, Any]:
        """Enhance content with podcast-specific information."""
        metadata = content.get("metadata", {})
        
        # Extract audio URL from enclosures
        audio_url = None
        audio_duration = None
        audio_size = None
        
        enclosures = metadata.get("enclosures", [])
        for enc in enclosures:
            if enc.get("type", "").startswith("audio/"):
                audio_url = enc.get("url")
                audio_size = enc.get("length")
                break
        
        for raw_duration in (
            metadata.get("itunes_duration"),
            metadata.get("duration"),
            content.get("itunes_duration"),
            content.get("duration"),
        ):
            audio_duration = self._parse_duration_seconds(raw_duration)
            if audio_duration is not None:
                break
        
        content["metadata"] = {
            **metadata,
            "audio_url": audio_url,
            "audio_size": audio_size,
            "audio_duration": audio_duration,
            "is_podcast": True
        }
        
        return content
    
    async def search_podcasts(self, query: str, limit: int = 10) -> List[Dict]:
        """Search for podcasts using iTunes Search API."""
        import aiohttp
        
        try:
            url = "https://itunes.apple.com/search"
            params = {
                "term": query,
                "media": "podcast",
                "limit": limit
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    data = await response.json()
            
            podcasts = []
            for result in data.get("results", []):
                podcasts.append({
                    "name": result.get("collectionName"),
                    "artist": result.get("artistName"),
                    "feed_url": result.get("feedUrl"),
                    "artwork": result.get("artworkUrl600") or result.get("artworkUrl100"),
                    "genre": result.get("primaryGenreName"),
                    "track_count": result.get("trackCount")
                })
            
            return podcasts
            
        except Exception as e:
            self.logger.error(f"Error searching podcasts: {e}")
            return []
    
    async def get_podcast_info(self, feed_url: str) -> Optional[Dict]:
        """Get podcast metadata from feed URL."""
        import feedparser
        
        try:
            feed = await asyncio.to_thread(feedparser.parse, feed_url)
            
            if feed.bozo and not feed.feed:
                return None
            
            podcast_feed = feed.feed
            
            return {
                "title": podcast_feed.get("title"),
                "description": podcast_feed.get("description") or podcast_feed.get("subtitle"),
                "author": podcast_feed.get("author") or podcast_feed.get("itunes_author"),
                "link": podcast_feed.get("link"),
                "image": (
                    podcast_feed.get("image", {}).get("href") or
                    podcast_feed.get("itunes_image", {}).get("href")
                ),
                "language": podcast_feed.get("language"),
                "categories": [
                    cat.get("term") for cat in podcast_feed.get("tags", [])
                ],
                "episode_count": len(feed.entries)
            }
            
        except Exception as e:
            self.logger.error(f"Error getting podcast info: {e}")
            return None
