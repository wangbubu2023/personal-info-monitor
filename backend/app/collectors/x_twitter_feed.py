"""Feed/API helpers for X collector."""

from __future__ import annotations

import asyncio
from calendar import timegm
from datetime import datetime, timezone
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import aiohttp
import feedparser

from app.models import Source
from app.utils.ssrf import assert_public_http_target


class XCollectorFeedMixin:
    """RSS/Nitter/API strategies and shared utilities."""

    async def _fetch_via_rsshub(self, username: str, source: Source) -> List[Dict[str, Any]]:
        feed_url = f"{self.rsshub_url}/twitter/user/{username}"
        self.logger.info(f"RSSHub feed URL: {feed_url}")
        feed_text = await self._http_get(feed_url)
        return self._parse_rss_feed(feed_text, username) if feed_text else []

    async def _fetch_via_nitter(self, username: str, source: Source) -> List[Dict[str, Any]]:
        for instance in self.nitter_instances:
            feed_url = f"{instance}/{username}/rss"
            self.logger.info(f"Trying Nitter: {feed_url}")
            try:
                feed_text = await self._http_get(feed_url, timeout=15)
                if not feed_text:
                    continue
                contents = self._parse_rss_feed(feed_text, username)
                if contents:
                    return contents
            except Exception as e:
                self.logger.warning(f"Nitter instance {instance} failed: {e}")
        return []

    async def _fetch_via_api(self, username: str, source: Source) -> List[Dict[str, Any]]:
        token = self.bearer_token
        if not token:
            self.logger.info("No Bearer Token configured, skipping API strategy")
            return []

        import tweepy

        if not self._tweepy_client:
            self._tweepy_client = tweepy.Client(bearer_token=token)
        client = self._tweepy_client

        user = client.get_user(username=username)
        if not user.data:
            self.logger.error(f"User not found via API: {username}")
            return []

        tweets = client.get_users_tweets(
            id=user.data.id,
            max_results=50,
            tweet_fields=["created_at", "public_metrics", "entities", "attachments"],
            expansions=["attachments.media_keys"],
            media_fields=["url", "preview_image_url", "type"],
            **self._build_api_since_id(source.last_content_id),
        )
        if not tweets.data:
            return []

        media_lookup = {}
        if tweets.includes and "media" in tweets.includes:
            for media in tweets.includes["media"]:
                media_lookup[media.media_key] = media

        contents = []
        for tweet in tweets.data:
            content = self._format_tweet_api(tweet, username, media_lookup)
            if self.validate_content(content):
                contents.append(content)
        return contents

    def _parse_rss_feed(self, feed_text: str, username: str) -> List[Dict[str, Any]]:
        feed = feedparser.parse(feed_text)
        if feed.bozo and not feed.entries:
            self.logger.warning(f"RSS parse error: {feed.bozo_exception}")
            return []

        contents = []
        for entry in feed.entries[:50]:
            content = self._format_rss_entry(entry, username)
            if self.validate_content(content):
                contents.append(content)

        contents.sort(key=lambda item: item.get("publish_time") or datetime.min, reverse=True)
        seen_ids = set()
        deduped = []
        for item in contents:
            eid = item.get("external_id")
            if eid and eid in seen_ids:
                continue
            if eid:
                seen_ids.add(eid)
            deduped.append(item)
        return deduped

    def _format_rss_entry(self, entry, username: str) -> Dict[str, Any]:
        publish_time = None
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            publish_time = datetime.fromtimestamp(timegm(entry.published_parsed), tz=timezone.utc).replace(tzinfo=None)
        elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
            publish_time = datetime.fromtimestamp(timegm(entry.updated_parsed), tz=timezone.utc).replace(tzinfo=None)

        raw_text = ""
        if hasattr(entry, "summary") and entry.summary:
            raw_text = entry.summary
        elif hasattr(entry, "content") and entry.content:
            raw_text = entry.content[0].value

        from bs4 import BeautifulSoup

        text = BeautifulSoup(raw_text, "html.parser").get_text(separator=" ").strip()
        title = entry.get("title", "")
        if not title or title == username:
            title = text[:80] + ("..." if len(text) > 80 else "")
        if not title:
            title = f"@{username} 的推文"

        url = entry.get("link", "") or f"https://x.com/{username}"
        url = self._normalize_tweet_url(url)
        external_id = (
            self._extract_tweet_id(url)
            or self._extract_tweet_id(entry.get("id", ""))
            or entry.get("id")
            or url
        )

        images = []
        from bs4 import BeautifulSoup as BS

        soup = BS(raw_text, "html.parser")
        for img in soup.find_all("img"):
            src = img.get("src")
            if src and ("twimg" in src or "pbs." in src):
                images.append(src)

        return {
            "external_id": external_id,
            "title": title,
            "content": text,
            "url": url,
            "publish_time": publish_time,
            "metadata": {
                "username": username,
                "images": images,
                "source_strategy": "rss",
            },
        }

    def _build_api_since_id(self, last_content_id: Optional[str]) -> Dict[str, Any]:
        tweet_id = self._extract_tweet_id(last_content_id or "")
        return {"since_id": tweet_id} if tweet_id else {}

    def _extract_tweet_id(self, value: str) -> Optional[str]:
        if not value:
            return None
        if re.fullmatch(r"\d{6,32}", value):
            return value
        match = re.search(r"/status/(\d{6,32})", value)
        if match:
            return match.group(1)
        match = re.search(r"[:/](\d{6,32})(?:\D|$)", value)
        if match:
            return match.group(1)
        return None

    def _normalize_tweet_url(self, url: str) -> str:
        try:
            parsed = urlparse(url)
            if "nitter" in parsed.netloc and "/status/" in parsed.path:
                parts = [p for p in parsed.path.split("/") if p]
                if len(parts) >= 3 and parts[1] == "status":
                    return f"https://x.com/{parts[0]}/status/{parts[2]}"
        except Exception as exc:
            self.logger.debug("Failed to normalize tweet url '%s': %s", url, exc)
            return url
        return url

    def _format_tweet_api(self, tweet, username: str, media_lookup: Dict) -> Dict[str, Any]:
        media = []
        if hasattr(tweet, "attachments") and tweet.attachments:
            for key in tweet.attachments.get("media_keys", []):
                if key in media_lookup:
                    media_item = media_lookup[key]
                    media.append(
                        {
                            "type": media_item.type,
                            "url": getattr(media_item, "url", None)
                            or getattr(media_item, "preview_image_url", None),
                        }
                    )

        urls = []
        if hasattr(tweet, "entities") and tweet.entities:
            for item in tweet.entities.get("urls", []):
                urls.append(
                    {
                        "short_url": item.get("url"),
                        "expanded_url": item.get("expanded_url"),
                        "display_url": item.get("display_url"),
                    }
                )

        metrics = {}
        if hasattr(tweet, "public_metrics") and tweet.public_metrics:
            metrics = {
                "likes": tweet.public_metrics.get("like_count", 0),
                "retweets": tweet.public_metrics.get("retweet_count", 0),
                "replies": tweet.public_metrics.get("reply_count", 0),
                "quotes": tweet.public_metrics.get("quote_count", 0),
            }

        text = tweet.text or ""
        title = text[:80] + ("..." if len(text) > 80 else "")
        return {
            "external_id": str(tweet.id),
            "title": title,
            "content": text,
            "url": f"https://x.com/{username}/status/{tweet.id}",
            "publish_time": tweet.created_at,
            "metadata": {
                "username": username,
                "media": media,
                "urls": urls,
                "metrics": metrics,
                "source_strategy": "api",
            },
        }

    def _extract_username(self, source: Source) -> Optional[str]:
        metadata = source.metadata_ or {}
        if "username" in metadata:
            return metadata["username"].lstrip("@")

        url = source.url
        if url.startswith("@"):
            return url[1:]

        match = re.search(r"(?:twitter\.com|x\.com)/(@)?([a-zA-Z0-9_]+)", url)
        if match:
            candidate = match.group(2)
            if candidate.lower() in {"home", "explore", "search", "i", "messages", "settings"}:
                return None
            return candidate
        if re.match(r"^[a-zA-Z0-9_]+$", url):
            return url
        return None

    async def _http_get(self, url: str, timeout: int = 20) -> Optional[str]:
        await assert_public_http_target(url)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                    allow_redirects=True,
                ) as response:
                    if response.status != 200:
                        self.logger.warning(f"HTTP {response.status} for {url}")
                        return None
                    return await response.text()
        except asyncio.TimeoutError:
            self.logger.warning(f"HTTP timeout: {url}")
            return None
        except Exception as e:
            self.logger.warning(f"HTTP error: {url} → {e}")
            return None
