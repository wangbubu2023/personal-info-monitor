"""GraphQL/config helpers for X collector."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import random
import re
from typing import Any, Dict, List, Optional

from app.models import Source


class XCollectorGraphQLMixin:
    """GraphQL strategy and shared config helpers."""

    def _get_settings(self):
        from app.config import get_settings

        return get_settings()

    @property
    def rsshub_url(self) -> str:
        if self._rsshub_url:
            return self._rsshub_url.rstrip("/")
        settings = self._get_settings()
        return getattr(settings, "rsshub_url", None) or "https://rsshub.app"

    @property
    def nitter_instances(self) -> List[str]:
        if self._nitter_instances:
            return self._nitter_instances
        settings = self._get_settings()
        raw = getattr(settings, "nitter_instances", None) or ""
        if raw:
            return [u.strip().rstrip("/") for u in raw.split(",") if u.strip()]
        return self.DEFAULT_NITTER_INSTANCES

    @property
    def bearer_token(self) -> Optional[str]:
        if self._bearer_token:
            return self._bearer_token
        settings = self._get_settings()
        return settings.x_bearer_token

    @property
    def x_auth_token(self) -> Optional[str]:
        settings = self._get_settings()
        return getattr(settings, "x_auth_token", None)

    @property
    def x_ct0_token(self) -> Optional[str]:
        settings = self._get_settings()
        return getattr(settings, "x_ct0_token", None)

    def _check_twikit_available(self) -> bool:
        if self._twikit_available is not None:
            return self._twikit_available
        try:
            import twikit  # noqa: F401

            self._twikit_available = True
            self._patch_twikit_transaction()
        except ImportError:
            self._twikit_available = False
            self.logger.warning("twikit 未安装，GraphQL 策略不可用。运行: pip install twikit")
        return self._twikit_available

    def _patch_twikit_transaction(self):
        import re
        from twikit.x_client_transaction.transaction import ClientTransaction

        if getattr(ClientTransaction, "_pim_patched", False):
            return

        original_get_indices = ClientTransaction.get_indices
        new_chunk_id_regex = re.compile(r'(\d+):\s*["\']ondemand\.s["\']')
        new_hash_regex_template = r'{chunk_id}:\s*["\']([a-f0-9]{{7,12}})["\']'

        async def patched_get_indices(self_ct, home_page_response, session, headers):
            try:
                return await original_get_indices(self_ct, home_page_response, session, headers)
            except Exception as exc:
                self.logger.debug("Falling back to new-format twikit transaction parser: %s", exc)

            from twikit.x_client_transaction.transaction import INDICES_REGEX

            html_text = str(home_page_response)
            chunk_id_match = new_chunk_id_regex.search(html_text)
            if not chunk_id_match:
                raise Exception("Couldn't find ondemand.s chunk ID in new format")

            chunk_id = chunk_id_match.group(1)
            hash_regex = re.compile(new_hash_regex_template.format(chunk_id=chunk_id))
            hash_match = hash_regex.search(html_text)
            if not hash_match:
                raise Exception(f"Couldn't find hash for chunk ID {chunk_id}")

            file_hash = hash_match.group(1)
            on_demand_url = f"https://abs.twimg.com/responsive-web/client-web/ondemand.s.{file_hash}a.js"
            on_demand_response = await session.request(method="GET", url=on_demand_url, headers=headers)
            key_byte_indices = [item.group(2) for item in INDICES_REGEX.finditer(str(on_demand_response.text))]
            if not key_byte_indices:
                raise Exception("Couldn't get KEY_BYTE indices from new-format ondemand.s")

            key_byte_indices = list(map(int, key_byte_indices))
            return key_byte_indices[0], key_byte_indices[1:]

        ClientTransaction.get_indices = patched_get_indices
        ClientTransaction._pim_patched = True
        self.logger.info("twikit ClientTransaction.get_indices 已修补（支持新 webpack 格式）")

    def _get_graphql_cookies(self, source: Source) -> Dict[str, str]:
        runtime_cookies = self.get_runtime_cookies(source)
        auth_token = runtime_cookies.get("auth_token") or runtime_cookies.get("AUTH_TOKEN")
        ct0 = runtime_cookies.get("ct0") or runtime_cookies.get("CT0")
        if auth_token and ct0:
            return {"auth_token": auth_token, "ct0": ct0}

        metadata = source.metadata_ or {}
        auth_token = metadata.get("x_auth_token") or metadata.get("auth_token")
        ct0 = metadata.get("x_ct0_token") or metadata.get("ct0")
        if auth_token and ct0:
            return {"auth_token": auth_token, "ct0": ct0}

        auth_token = self.x_auth_token
        ct0 = self.x_ct0_token
        if auth_token and ct0:
            return {"auth_token": auth_token, "ct0": ct0}
        return {}

    async def _get_twikit_client(self, source: Source):
        from twikit import Client as TwikitClient

        cookies = self._get_graphql_cookies(source)
        if not cookies:
            return None

        client = TwikitClient("en-US")
        client.set_cookies(cookies)
        return client

    async def _fetch_via_graphql(self, username: str, source: Source) -> List[Dict[str, Any]]:
        if not self._check_twikit_available():
            return []

        cookies = self._get_graphql_cookies(source)
        if not cookies:
            self.logger.info("GraphQL 策略跳过：未配置 X_AUTH_TOKEN / X_CT0_TOKEN")
            return []

        try:
            from app.tasks.fetch_auth_helpers import cookies_appear_valid

            if not await cookies_appear_valid("https://x.com", cookies):
                self.logger.warning(f"GraphQL: X Cookie 可能已失效，跳过 @{username}")
                return []
        except Exception as e:
            self.logger.debug(f"GraphQL: Cookie 预检异常（继续尝试）: {e}")

        try:
            client = await self._get_twikit_client(source)
            if not client:
                return []

            self.logger.info(f"GraphQL: 查找用户 @{username}")
            user = await client.get_user_by_screen_name(username)
            if not user:
                self.logger.warning(f"GraphQL: 用户 @{username} 未找到")
                return []

            await asyncio.sleep(random.uniform(0.5, 1.5))
            self.logger.info(f"GraphQL: 正在获取 @{username} 的推文 (user_id={user.id})")
            tweets = await client.get_user_tweets(user.id, "Tweets", count=50)
            if not tweets:
                self.logger.info(f"GraphQL: @{username} 没有新推文")
                return []

            contents = [
                content
                for content in (self._format_tweet_graphql(tweet, username) for tweet in tweets)
                if self.validate_content(content)
            ]
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

            self.logger.info(f"GraphQL: @{username} 成功获取 {len(deduped)} 条推文")
            return deduped
        except Exception as e:
            self.logger.warning(f"GraphQL 策略失败: {e}")
            return []

    def _format_tweet_graphql(self, tweet, username: str) -> Dict[str, Any]:
        text = getattr(tweet, "full_text", None) or getattr(tweet, "text", "") or ""
        title = text[:80] + ("..." if len(text) > 80 else "")
        if not title:
            title = f"@{username} 的推文"

        publish_time = getattr(tweet, "created_at_datetime", None)
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
                media_item = {"type": type(media).__name__.lower()}
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

        metrics = {}
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

        content_type = "article" if self._extract_article_urls(text) else "tweet"
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
