"""YouTube content collector using yt-dlp (no API key required)."""

import asyncio
from calendar import timegm
from datetime import timezone
import html
import json
import re
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional
from urllib.parse import parse_qs, urlparse

import feedparser

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
    _CAPTION_BUCKETS = ("requested_subtitles", "subtitles", "automatic_captions")
    _LANG_PRIORITY = ("en", "en-us", "en-gb", "zh", "zh-hans", "zh-hant")

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
        except ImportError as exc:
            from app.domains.fetch.failures import FetchFailureError, classify_exception

            self.logger.error("yt-dlp is not installed. Please add yt-dlp to requirements.txt")
            raise FetchFailureError(classify_exception(exc)) from exc

        metadata = source.metadata_ or {}
        video_count = int(metadata.get("video_count", self.DEFAULT_VIDEO_COUNT))

        feed_contents = await self._fetch_from_feed(source, video_count)
        if feed_contents:
            self.logger.info(f"YouTube RSS fetched {len(feed_contents)} videos from {source.url}")
            return feed_contents

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
                if self._is_channel_tab_entry(entry):
                    self.logger.debug("Skipping YouTube channel tab entry: %s", entry.get("url") or entry.get("id"))
                    continue
                content = self._format_entry(entry, info)
                if self.validate_content(content):
                    results.append(content)

            self.logger.info(f"yt-dlp fetched {len(results)} videos from {source.url}")
            return results

        except Exception as exc:
            from app.domains.fetch.failures import FetchFailureError, classify_exception

            self.logger.error(f"yt-dlp failed for {source.url}: {exc}")
            raise FetchFailureError(classify_exception(exc)) from exc

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _normalise_channel_url(self, url: str) -> str:
        """Ensure the URL ends at the channel root (strip /featured etc.)."""
        import re
        url = url.rstrip("/")
        url = re.sub(r"/(videos|featured|about|community|shorts)$", "", url)
        return url

    @staticmethod
    def _looks_like_channel_id(value: str | None) -> bool:
        return bool(value and re.fullmatch(r"UC[a-zA-Z0-9_-]{22}", str(value)))

    @staticmethod
    def _looks_like_video_id(value: str | None) -> bool:
        return bool(value and re.fullmatch(r"[a-zA-Z0-9_-]{11}", str(value)))

    @staticmethod
    def _extract_playlist_id(url: str) -> str | None:
        try:
            parsed = urlparse(url)
        except ValueError:
            return None
        if "youtube.com" not in (parsed.netloc or "").lower():
            return None
        playlist_id = parse_qs(parsed.query).get("list", [None])[0]
        return playlist_id or None

    @classmethod
    def _extract_channel_id(cls, url: str) -> str | None:
        match = re.search(r"youtube\.com/channel/(UC[a-zA-Z0-9_-]{22})", url)
        return match.group(1) if match else None

    @staticmethod
    def _extract_feed_username(url: str) -> str | None:
        match = re.search(r"youtube\.com/(?:c|user)/([a-zA-Z0-9_-]+)", url)
        return match.group(1) if match else None

    def _feed_url_candidates(self, source: Source) -> list[str]:
        metadata = source.metadata_ if isinstance(source.metadata_, dict) else {}
        candidates: list[str] = []

        for key in ("rss_url", "feed_url"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                candidates.append(value.strip())

        rss_urls = metadata.get("rss_urls")
        if isinstance(rss_urls, Mapping):
            candidates.extend(str(value).strip() for value in rss_urls.values() if value)
        elif isinstance(rss_urls, list):
            candidates.extend(str(value).strip() for value in rss_urls if value)

        playlist_id = self._extract_playlist_id(source.url)
        if playlist_id:
            candidates.append(f"https://www.youtube.com/feeds/videos.xml?playlist_id={playlist_id}")

        channel_id = self._extract_channel_id(source.url)
        if not channel_id and self._looks_like_channel_id(getattr(source, "last_content_id", None)):
            channel_id = str(source.last_content_id)
        if channel_id:
            candidates.append(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}")

        username = self._extract_feed_username(source.url)
        if username:
            candidates.append(f"https://www.youtube.com/feeds/videos.xml?user={username}")

        seen = set()
        deduped: list[str] = []
        for candidate in candidates:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            deduped.append(candidate)
        return deduped

    async def _fetch_from_feed(self, source: Source, count: int) -> list[dict[str, Any]]:
        for feed_url in self._feed_url_candidates(source):
            try:
                await self._check_ssrf(feed_url)
                feed = await asyncio.to_thread(feedparser.parse, feed_url)
                status = int(getattr(feed, "status", 0) or 0)
                if status >= 400 or (feed.bozo and not feed.entries):
                    self.logger.debug("YouTube RSS candidate unavailable: %s", feed_url)
                    continue
                contents = []
                for entry in feed.entries[:count]:
                    content = self._format_feed_entry(entry, feed, feed_url)
                    if self.validate_content(content):
                        contents.append(content)
                if contents:
                    return contents
            except (OSError, TimeoutError, TypeError, ValueError) as exc:
                self.logger.debug("YouTube RSS candidate failed for %s: %s", feed_url, exc)
                continue
        return []

    def _format_feed_entry(self, entry: Mapping[str, Any], feed: Mapping[str, Any], feed_url: str) -> Dict[str, Any]:
        video_id = entry.get("yt_videoid") or entry.get("yt_videoId") or ""
        if not video_id:
            raw_id = str(entry.get("id") or "")
            if raw_id.startswith("yt:video:"):
                video_id = raw_id.rsplit(":", 1)[-1]
        link = entry.get("link") or (f"https://www.youtube.com/watch?v={video_id}" if video_id else "")
        title = str(entry.get("title") or "").strip()
        description = str(entry.get("summary") or entry.get("description") or "").strip()

        publish_time = None
        published_parsed = entry.get("published_parsed") or entry.get("updated_parsed")
        if published_parsed:
            publish_time = datetime.fromtimestamp(timegm(published_parsed), tz=timezone.utc).replace(tzinfo=None)

        channel = (
            entry.get("author")
            or entry.get("channel")
            or getattr(feed, "feed", {}).get("title", "")
            or "YouTube"
        )
        thumbnail = None
        media_thumbnail = entry.get("media_thumbnail") or []
        if media_thumbnail and isinstance(media_thumbnail, list):
            thumbnail = media_thumbnail[-1].get("url")

        return {
            "external_id": video_id or entry.get("id") or link or title,
            "title": title,
            "content": description,
            "url": link,
            "publish_time": publish_time,
            "metadata": {
                "channel": channel,
                "video_id": video_id,
                "thumbnail": thumbnail,
                "source_strategy": "youtube_rss",
                "youtube_feed_url": feed_url,
                "youtube_transcript_status": "missing",
            },
        }

    def _is_channel_tab_entry(self, entry: Mapping[str, Any]) -> bool:
        entry_id = str(entry.get("id") or entry.get("display_id") or "")
        if not self._looks_like_channel_id(entry_id):
            return False
        entry_url = str(entry.get("url") or entry.get("webpage_url") or "")
        if re.search(r"/(videos|shorts|streams|playlists|community)(?:$|[/?#])", entry_url):
            return True
        return not self._looks_like_video_id(entry_id) and not entry.get("upload_date")

    def _parse_upload_date(self, upload_date: Optional[str]) -> Optional[datetime]:
        """Parse yt-dlp's YYYYMMDD upload_date string into a naive UTC datetime."""
        if not upload_date:
            return None
        try:
            return datetime.strptime(upload_date, "%Y%m%d")
        except Exception as exc:
            self.logger.debug("Failed to parse upload_date '%s': %s", upload_date, exc)
            return None

    def _caption_tracks(self, entry: Mapping[str, Any]) -> tuple[str | None, str | None, list[Mapping[str, Any]]]:
        for bucket_name in self._CAPTION_BUCKETS:
            bucket = entry.get(bucket_name)
            if not isinstance(bucket, Mapping) or not bucket:
                continue
            languages = {str(lang).lower(): lang for lang in bucket.keys()}
            ordered = [languages[lang] for lang in self._LANG_PRIORITY if lang in languages]
            ordered.extend(lang for key, lang in languages.items() if lang not in ordered)
            for lang in ordered:
                raw_tracks = bucket.get(lang)
                if isinstance(raw_tracks, Mapping):
                    tracks = [raw_tracks]
                elif isinstance(raw_tracks, list):
                    tracks = [track for track in raw_tracks if isinstance(track, Mapping)]
                else:
                    tracks = []
                if tracks:
                    return bucket_name, str(lang), tracks
        return None, None, []

    @staticmethod
    def _caption_json_text(data: str) -> str:
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError:
            return ""
        events = parsed.get("events") if isinstance(parsed, Mapping) else parsed
        if not isinstance(events, list):
            return ""
        parts: list[str] = []
        for event in events:
            if not isinstance(event, Mapping):
                continue
            segments = event.get("segs")
            if not isinstance(segments, list):
                continue
            for segment in segments:
                if isinstance(segment, Mapping):
                    text = str(segment.get("utf8") or "").strip()
                    if text:
                        parts.append(text)
        return " ".join(parts)

    @staticmethod
    def _caption_vtt_text(data: str) -> str:
        lines: list[str] = []
        for raw_line in data.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            upper = line.upper()
            if upper.startswith(("WEBVTT", "NOTE", "STYLE", "REGION", "KIND:", "LANGUAGE:")):
                continue
            if "-->" in line or line.isdigit():
                continue
            line = re.sub(r"<[^>]+>", "", line)
            line = html.unescape(line).strip()
            if line and (not lines or lines[-1] != line):
                lines.append(line)
        return " ".join(lines)

    def _caption_track_text(self, tracks: list[Mapping[str, Any]]) -> tuple[str, bool]:
        saw_url = False
        parts: list[str] = []
        for track in tracks:
            if track.get("url"):
                saw_url = True
            fragments = track.get("fragments")
            if isinstance(fragments, list):
                fragment_text = " ".join(
                    str(fragment.get("text") or "").strip()
                    for fragment in fragments
                    if isinstance(fragment, Mapping) and fragment.get("text")
                ).strip()
                if fragment_text:
                    parts.append(fragment_text)
            data = track.get("data") or track.get("text")
            if isinstance(data, str) and data.strip():
                extracted = self._caption_json_text(data) or self._caption_vtt_text(data)
                if extracted:
                    parts.append(extracted)
        text = " ".join(part for part in parts if part).strip()
        return re.sub(r"\s+", " ", text), saw_url

    def _extract_transcript(self, entry: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        bucket, language, tracks = self._caption_tracks(entry)
        if not tracks:
            return "", {"youtube_transcript_status": "missing"}
        transcript, saw_url = self._caption_track_text(tracks)
        metadata = {
            "youtube_transcript_status": "inline" if transcript else "available_url_only" if saw_url else "empty",
            "youtube_transcript_source": bucket,
            "youtube_transcript_language": language,
        }
        if transcript:
            metadata["youtube_transcript_chars"] = len(transcript)
        return transcript, metadata

    def _format_entry(self, entry: Dict, parent_info: Dict) -> Dict[str, Any]:
        """Convert a yt-dlp entry dict into the standard content format."""
        video_id = entry.get("id") or entry.get("display_id") or ""
        title = (entry.get("title") or "").strip()
        description = (entry.get("description") or entry.get("summary") or "").strip()
        transcript, transcript_metadata = self._extract_transcript(entry)
        body = description
        if transcript:
            body = f"{description}\n\nTranscript:\n{transcript}" if description else transcript
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

        metadata = {
            "channel": channel,
            "video_id": video_id,
            "thumbnail": thumbnail,
            "source_strategy": "yt_dlp",
            **transcript_metadata,
        }
        if transcript:
            metadata["youtube_description"] = description
            metadata["article_fulltext"] = True
            metadata["fulltext_status"] = "full"

        return {
            "external_id": video_id or watch_url or title,
            "title": title or f"YouTube video {video_id}",
            "content": body,
            "url": watch_url,
            "publish_time": publish_time,
            "metadata": metadata,
        }
