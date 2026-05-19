"""Formatters that turn raw X/Twitter payloads into canonical content dicts.

All functions here are pure: they never touch the network or collector
state. The main collector applies validation / dedup on top of the output.
"""

from __future__ import annotations

from calendar import timegm
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.domains.fetch.collectors.x_twitter_text import (
    extract_article_urls,
    extract_tweet_id,
    normalize_tweet_url,
)


def format_tweet_graphql(tweet, username: str) -> Dict[str, Any]:
    """Shape a twikit GraphQL tweet object into a collector content dict."""
    text = getattr(tweet, "full_text", None) or getattr(tweet, "text", "") or ""
    title = text[:80] + ("..." if len(text) > 80 else "")
    if not title:
        title = f"@{username} 的推文"

    publish_time: Optional[datetime] = getattr(tweet, "created_at_datetime", None)
    if publish_time and publish_time.tzinfo is not None:
        publish_time = publish_time.astimezone(timezone.utc).replace(tzinfo=None)
    if not publish_time and hasattr(tweet, "created_at"):
        try:
            publish_time = datetime.strptime(
                tweet.created_at, "%a %b %d %H:%M:%S %z %Y"
            ).astimezone(timezone.utc).replace(tzinfo=None)
        except (ValueError, AttributeError):
            publish_time = None

    tweet_id = str(tweet.id)
    url = f"https://x.com/{username}/status/{tweet_id}"

    media_list = []
    if hasattr(tweet, "media") and tweet.media:
        for media in tweet.media:
            media_item: Dict[str, Any] = {"type": type(media).__name__.lower()}
            if hasattr(media, "url"):
                media_item["url"] = media.url
            elif hasattr(media, "media_url_https"):
                media_item["url"] = media.media_url_https
            if hasattr(media, "thumbnail_url"):
                media_item["thumbnail"] = media.thumbnail_url
            media_list.append(media_item)

    urls_list = []
    if hasattr(tweet, "urls") and tweet.urls:
        for item in tweet.urls:
            if isinstance(item, dict):
                urls_list.append(
                    {
                        "expanded_url": item.get("expanded_url", ""),
                        "display_url": item.get("display_url", ""),
                    }
                )
            elif isinstance(item, str):
                urls_list.append({"expanded_url": item})

    metrics: Dict[str, Any] = {}
    for attr, key in [
        ("favorite_count", "likes"),
        ("retweet_count", "retweets"),
        ("reply_count", "replies"),
        ("quote_count", "quotes"),
        ("view_count", "views"),
        ("bookmark_count", "bookmarks"),
    ]:
        val = getattr(tweet, attr, None)
        if val is not None:
            metrics[key] = val

    content_type = "article" if extract_article_urls(text) else "tweet"
    is_retweet = hasattr(tweet, "retweeted_tweet") and tweet.retweeted_tweet is not None
    if is_retweet:
        rt = tweet.retweeted_tweet
        rt_user = getattr(rt, "user", None)
        rt_username = getattr(rt_user, "screen_name", "unknown") if rt_user else "unknown"
        text = f"RT @{rt_username}: {getattr(rt, 'full_text', None) or getattr(rt, 'text', '') or ''}"
        title = text[:80] + ("..." if len(text) > 80 else "")

    return {
        "external_id": tweet_id,
        "title": title,
        "content": text,
        "url": url,
        "publish_time": publish_time,
        "metadata": {
            "username": username,
            "media": media_list,
            "urls": urls_list,
            "metrics": metrics,
            "content_type": content_type,
            "source_strategy": "graphql",
            "lang": getattr(tweet, "lang", None),
            "hashtags": getattr(tweet, "hashtags", []) or [],
            "is_retweet": is_retweet,
        },
    }


def format_rss_entry(entry, username: str, logger=None) -> Dict[str, Any]:
    """Convert a feedparser RSS entry into the collector content dict shape."""
    from bs4 import BeautifulSoup

    publish_time: Optional[datetime] = None
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        publish_time = datetime.fromtimestamp(timegm(entry.published_parsed), tz=timezone.utc).replace(tzinfo=None)
    elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
        publish_time = datetime.fromtimestamp(timegm(entry.updated_parsed), tz=timezone.utc).replace(tzinfo=None)

    raw_text = ""
    if hasattr(entry, "summary") and entry.summary:
        raw_text = entry.summary
    elif hasattr(entry, "content") and entry.content:
        raw_text = entry.content[0].value

    text = BeautifulSoup(raw_text, "html.parser").get_text(separator=" ").strip()
    title = entry.get("title", "")
    if not title or title == username:
        title = text[:80] + ("..." if len(text) > 80 else "")
    if not title:
        title = f"@{username} 的推文"

    url = entry.get("link", "") or f"https://x.com/{username}"
    url = normalize_tweet_url(url, logger=logger)
    external_id = (
        extract_tweet_id(url)
        or extract_tweet_id(entry.get("id", ""))
        or entry.get("id")
        or url
    )

    images = []
    soup = BeautifulSoup(raw_text, "html.parser")
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


def format_tweet_api(tweet, username: str, media_lookup: Dict) -> Dict[str, Any]:
    """Shape a Tweepy v2 tweet object into a collector content dict."""
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

    metrics: Dict[str, Any] = {}
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
