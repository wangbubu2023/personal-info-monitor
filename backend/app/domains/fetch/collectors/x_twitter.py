"""X (Twitter) unified content collector.

The fetch strategies (GraphQL / RSSHub / Nitter / API / Playwright
hydration) still live on :class:`XCollector`. Pure helpers have been moved
into dedicated sibling modules so this file can focus on orchestration:

* :mod:`app.domains.fetch.collectors.x_twitter_text` — URL / ID parsing,
  cookie construction, text cleaning.
* :mod:`app.domains.fetch.collectors.x_twitter_formatters` — tweet →
  content dict formatters for GraphQL, RSS, and REST payloads.

Underscore-prefixed methods are kept as thin delegators so existing tests
that exercise them via ``collector._extract_article_urls`` etc. continue
to work unchanged.
"""

from __future__ import annotations

import asyncio
import random
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiohttp
import feedparser

from app.domains.fetch.collectors.base import BaseCollector
from app.domains.fetch.collectors.x_twitter_formatters import (
    format_rss_entry,
    format_tweet_api,
    format_tweet_graphql,
)
from app.domains.fetch.collectors.x_twitter_text import (
    ARTICLE_URL_RE,
    build_api_since_id,
    build_title_from_text,
    build_x_cookie_items,
    clean_article_text,
    extract_article_urls,
    extract_tweet_id,
    extract_username_from_url,
    normalize_tweet_url,
    title_looks_like_url,
)
from app.models import Source
from app.utils.http import permissive_session_kwargs
from app.platform.security.ssrf import fetch_public_http_text


class XCollector(BaseCollector):
    """Collector for X (Twitter) accounts using multiple fallback strategies."""

    DEFAULT_NITTER_INSTANCES = [
        "https://nitter.privacydev.net",
        "https://nitter.poast.org",
        "https://nitter.woodland.cafe",
    ]
    ARTICLE_URL_RE = ARTICLE_URL_RE

    def __init__(
        self,
        rsshub_url: Optional[str] = None,
        nitter_instances: Optional[List[str]] = None,
        bearer_token: Optional[str] = None,
    ):
        super().__init__()
        self._rsshub_url = rsshub_url
        self._nitter_instances = nitter_instances
        self._bearer_token = bearer_token
        self._tweepy_client = None
        self._twikit_client = None
        self._twikit_available: Optional[bool] = None

    async def fetch(self, source: Source) -> List[Dict[str, Any]]:
        """Fetch tweets from a user, trying configured strategies in order."""
        await self._check_ssrf(source.url)
        username = self._extract_username(source)
        if not username:
            self.logger.error(f"Could not extract username from source: {source.url}")
            return []

        self.logger.info(f"Fetching X account: @{username}")
        metadata = source.metadata_ or {}
        strategy = metadata.get("strategy") or (metadata.get("probe") or {}).get("strategy", "graphql")
        handlers = {
            "graphql": self._fetch_via_graphql,
            "rsshub": self._fetch_via_rsshub,
            "nitter": self._fetch_via_nitter,
            "api": self._fetch_via_api,
        }
        ordered = [strategy] + [name for name in ["graphql", "rsshub", "nitter", "api"] if name != strategy]

        for strategy_name in ordered:
            handler = handlers.get(strategy_name)
            if not handler:
                continue
            try:
                self.logger.info(f"Trying strategy: {strategy_name} for @{username}")
                contents = await handler(username, source)
                contents = await self._enrich_article_content(contents, source)
                if contents:
                    self.logger.info(
                        f"Strategy '{strategy_name}' succeeded: {len(contents)} items from @{username}"
                    )
                    return contents
                self.logger.info(f"Strategy '{strategy_name}' returned 0 items, trying next...")
            except Exception as exc:  # noqa: BLE001 - each strategy may raise a different surface
                self.logger.warning(f"Strategy '{strategy_name}' failed: {exc}")

        self.logger.error(f"All strategies exhausted for @{username}")
        return []

    # ------------------------------------------------------------------
    # Configuration helpers.
    # ------------------------------------------------------------------

    def _get_settings(self):
        from app.config import get_settings

        return get_settings()

    def rsshub_url(self) -> str:
        if self._rsshub_url:
            return self._rsshub_url.rstrip("/")
        settings = self._get_settings()
        return getattr(settings, "rsshub_url", None) or "https://rsshub.app"

    def nitter_instances(self) -> List[str]:
        if self._nitter_instances:
            return self._nitter_instances
        settings = self._get_settings()
        raw = getattr(settings, "nitter_instances", None) or ""
        if raw:
            return [u.strip().rstrip("/") for u in raw.split(",") if u.strip()]
        return self.DEFAULT_NITTER_INSTANCES

    def bearer_token(self) -> Optional[str]:
        if self._bearer_token:
            return self._bearer_token
        settings = self._get_settings()
        return settings.x_bearer_token

    def x_auth_token(self) -> Optional[str]:
        settings = self._get_settings()
        return getattr(settings, "x_auth_token", None)

    def x_ct0_token(self) -> Optional[str]:
        settings = self._get_settings()
        return getattr(settings, "x_ct0_token", None)

    # ------------------------------------------------------------------
    # twikit bootstrap.
    # ------------------------------------------------------------------

    def _check_twikit_available(self) -> bool:
        if self._twikit_available is not None:
            return self._twikit_available
        try:
            import twikit  # noqa: F401

            self._twikit_available = True
            self._patch_twikit_transaction()
            self._patch_twikit_user()
        except ImportError:
            self._twikit_available = False
            self.logger.warning("twikit 未安装，GraphQL 策略不可用。运行: pip install twikit")
        return self._twikit_available

    def _patch_twikit_user(self):
        """Defensively normalise ``User`` payloads before twikit parses them.

        twikit 2.3.3's ``User.__init__`` hard-indexes several ``legacy`` fields
        that X has started returning selectively (notably
        ``legacy.entities.description.urls`` and, for some sparse accounts,
        ``withheld_in_countries`` / ``pinned_tweet_ids_str``). When the key
        is missing we hit ``KeyError: 'urls'`` inside
        ``client.get_user_by_screen_name`` and the whole GraphQL strategy
        fails — even though the HTTP request itself returned 200 with valid
        cookies. Rather than fork twikit, wrap ``__init__`` to backfill the
        missing keys with empty-but-type-correct defaults so the upstream
        assignments succeed.
        """
        from twikit.user import User

        original_init = User.__init__
        if getattr(original_init, "_pim_patched", False):
            return

        def patched_init(self_user, client, data):
            legacy = data.get("legacy")
            if isinstance(legacy, dict):
                entities = legacy.setdefault("entities", {})
                if isinstance(entities, dict):
                    desc = entities.setdefault("description", {})
                    if isinstance(desc, dict):
                        desc.setdefault("urls", [])
                    url_block = entities.setdefault("url", {})
                    if isinstance(url_block, dict):
                        url_block.setdefault("urls", [])
                legacy.setdefault("withheld_in_countries", [])
                legacy.setdefault("pinned_tweet_ids_str", [])
                legacy.setdefault("location", "")
                legacy.setdefault("description", "")
                legacy.setdefault("fast_followers_count", 0)
                legacy.setdefault("normal_followers_count", 0)
                legacy.setdefault("media_count", 0)
                legacy.setdefault("possibly_sensitive", False)
                legacy.setdefault("can_dm", False)
                legacy.setdefault("can_media_tag", False)
                legacy.setdefault("want_retweets", False)
                legacy.setdefault("has_custom_timelines", False)
                legacy.setdefault("is_translator", False)
                legacy.setdefault("translator_type", "none")
            return original_init(self_user, client, data)

        patched_init._pim_patched = True
        User.__init__ = patched_init
        self.logger.info("twikit User.__init__ 已修补（容忍 legacy.entities 缺失字段）")

    def _patch_twikit_transaction(self):
        from twikit.x_client_transaction.transaction import ClientTransaction

        if getattr(ClientTransaction, "_pim_patched", False):
            return

        original_get_indices = ClientTransaction.get_indices
        new_chunk_id_regex = re.compile(r'(\d+):\s*["\']ondemand\.s["\']')
        new_hash_regex_template = r'{chunk_id}:\s*["\']([a-f0-9]{{7,12}})["\']'

        async def patched_get_indices(self_ct, home_page_response, session, headers):
            try:
                return await original_get_indices(self_ct, home_page_response, session, headers)
            except Exception as exc:  # noqa: BLE001 - upstream raises mixed errors; we only care about fallback path
                self.logger.debug("Falling back to new-format twikit transaction parser: %s", exc)

            from twikit.x_client_transaction.transaction import INDICES_REGEX

            html_text = str(home_page_response)
            chunk_id_match = new_chunk_id_regex.search(html_text)
            if not chunk_id_match:
                raise RuntimeError("Couldn't find ondemand.s chunk ID in new format")

            chunk_id = chunk_id_match.group(1)
            hash_regex = re.compile(new_hash_regex_template.format(chunk_id=chunk_id))
            hash_match = hash_regex.search(html_text)
            if not hash_match:
                raise RuntimeError(f"Couldn't find hash for chunk ID {chunk_id}")

            file_hash = hash_match.group(1)
            on_demand_url = f"https://abs.twimg.com/responsive-web/client-web/ondemand.s.{file_hash}a.js"
            on_demand_response = await session.request(method="GET", url=on_demand_url, headers=headers)
            key_byte_indices = [item.group(2) for item in INDICES_REGEX.finditer(str(on_demand_response.text))]
            if not key_byte_indices:
                raise RuntimeError("Couldn't get KEY_BYTE indices from new-format ondemand.s")

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

        auth_token = self.x_auth_token()
        ct0 = self.x_ct0_token()
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

    # ------------------------------------------------------------------
    # Strategy handlers.
    # ------------------------------------------------------------------

    async def _fetch_via_graphql(self, username: str, source: Source) -> List[Dict[str, Any]]:
        if not self._check_twikit_available():
            return []

        cookies = self._get_graphql_cookies(source)
        if not cookies:
            self.logger.info("GraphQL 策略跳过：未配置 X_AUTH_TOKEN / X_CT0_TOKEN")
            return []

        try:
            from app.platform.auth.cookies import cookies_appear_valid

            if not await cookies_appear_valid("https://x.com", cookies):
                self.logger.warning(f"GraphQL: X Cookie 可能已失效，跳过 @{username}")
                return []
        except Exception as exc:  # noqa: BLE001 - cookie precheck is best-effort
            self.logger.debug(f"GraphQL: Cookie 预检异常（继续尝试）: {exc}")

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
                for content in (format_tweet_graphql(tweet, username) for tweet in tweets)
                if self.validate_content(content)
            ]
            contents.sort(key=lambda item: item.get("publish_time") or datetime.min, reverse=True)

            seen_ids: set = set()
            deduped: List[Dict[str, Any]] = []
            for item in contents:
                eid = item.get("external_id")
                if eid and eid in seen_ids:
                    continue
                if eid:
                    seen_ids.add(eid)
                deduped.append(item)

            self.logger.info(f"GraphQL: @{username} 成功获取 {len(deduped)} 条推文")
            return deduped
        except Exception as exc:  # noqa: BLE001 - twikit surfaces varied errors on auth / network failures
            self.logger.warning(f"GraphQL 策略失败: {exc}")
            return []

    async def _fetch_via_rsshub(self, username: str, source: Source) -> List[Dict[str, Any]]:
        feed_url = f"{self.rsshub_url()}/twitter/user/{username}"
        self.logger.info(f"RSSHub feed URL: {feed_url}")
        feed_text = await self._http_get(feed_url)
        return self._parse_rss_feed(feed_text, username) if feed_text else []

    async def _fetch_via_nitter(self, username: str, source: Source) -> List[Dict[str, Any]]:
        for instance in self.nitter_instances():
            feed_url = f"{instance}/{username}/rss"
            self.logger.info(f"Trying Nitter: {feed_url}")
            try:
                feed_text = await self._http_get(feed_url, timeout=15)
                if not feed_text:
                    continue
                contents = self._parse_rss_feed(feed_text, username)
                if contents:
                    return contents
            except Exception as exc:  # noqa: BLE001 - each Nitter mirror fails differently; keep trying others
                self.logger.warning(f"Nitter instance {instance} failed: {exc}")
        return []

    async def _fetch_via_api(self, username: str, source: Source) -> List[Dict[str, Any]]:
        token = self.bearer_token()
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

        media_lookup: Dict[str, Any] = {}
        if tweets.includes and "media" in tweets.includes:
            for media in tweets.includes["media"]:
                media_lookup[media.media_key] = media

        contents: List[Dict[str, Any]] = []
        for tweet in tweets.data:
            content = format_tweet_api(tweet, username, media_lookup)
            if self.validate_content(content):
                contents.append(content)
        return contents

    # ------------------------------------------------------------------
    # RSS feed parsing.
    # ------------------------------------------------------------------

    def _parse_rss_feed(self, feed_text: str, username: str) -> List[Dict[str, Any]]:
        feed = feedparser.parse(feed_text)
        if feed.bozo and not feed.entries:
            self.logger.warning(f"RSS parse error: {feed.bozo_exception}")
            return []

        contents: List[Dict[str, Any]] = []
        for entry in feed.entries[:50]:
            content = format_rss_entry(entry, username, logger=self.logger)
            if self.validate_content(content):
                contents.append(content)

        contents.sort(key=lambda item: item.get("publish_time") or datetime.min, reverse=True)
        seen_ids: set = set()
        deduped: List[Dict[str, Any]] = []
        for item in contents:
            eid = item.get("external_id")
            if eid and eid in seen_ids:
                continue
            if eid:
                seen_ids.add(eid)
            deduped.append(item)
        return deduped

    # ------------------------------------------------------------------
    # Pure-helper delegators — kept for backward-compat with existing tests.
    # ------------------------------------------------------------------

    def _format_tweet_graphql(self, tweet, username: str) -> Dict[str, Any]:
        return format_tweet_graphql(tweet, username)

    def _format_rss_entry(self, entry, username: str) -> Dict[str, Any]:
        return format_rss_entry(entry, username, logger=self.logger)

    def _format_tweet_api(self, tweet, username: str, media_lookup: Dict) -> Dict[str, Any]:
        return format_tweet_api(tweet, username, media_lookup)

    def _build_api_since_id(self, last_content_id: Optional[str]) -> Dict[str, Any]:
        return build_api_since_id(last_content_id)

    def _extract_tweet_id(self, value: str) -> Optional[str]:
        return extract_tweet_id(value)

    def _normalize_tweet_url(self, url: str) -> str:
        return normalize_tweet_url(url, logger=self.logger)

    def _extract_username(self, source: Source) -> Optional[str]:
        return extract_username_from_url(source.url, source.metadata_)

    def _extract_article_urls(self, text: str) -> List[str]:
        return extract_article_urls(text)

    def _build_x_cookie_items(self, cookies: Dict[str, str]) -> List[Dict[str, Any]]:
        return build_x_cookie_items(cookies)

    def _clean_article_text(self, text: str) -> Optional[str]:
        return clean_article_text(text)

    def _title_looks_like_url(self, title: str) -> bool:
        return title_looks_like_url(title)

    def _build_title_from_text(self, text: str) -> str:
        return build_title_from_text(text)

    # ------------------------------------------------------------------
    # HTTP + article hydration.
    # ------------------------------------------------------------------

    async def _http_get(self, url: str, timeout: int = 20) -> Optional[str]:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        }
        try:
            async with aiohttp.ClientSession(**permissive_session_kwargs()) as session:
                response = await fetch_public_http_text(
                    session,
                    url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                )
                if response.status != 200:
                    self.logger.warning(f"HTTP {response.status} for {url}")
                    return None
                return response.text
        except asyncio.TimeoutError:
            self.logger.warning(f"HTTP timeout: {url}")
            return None
        except (aiohttp.ClientError, OSError, ValueError) as exc:
            self.logger.warning(f"HTTP error: {url} → {exc}")
            return None

    async def _enrich_article_content(
        self, contents: List[Dict[str, Any]], source
    ) -> List[Dict[str, Any]]:
        if not contents:
            return contents

        metadata = source.metadata_ or {}
        if metadata.get("fetch_x_articles", True) is False:
            return contents

        article_limit = int(metadata.get("x_article_fetch_limit", 8))
        if article_limit <= 0:
            return contents

        article_map: Dict[str, List[int]] = {}
        for idx, item in enumerate(contents):
            item_meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            url_texts: List[str] = [
                str(item.get("title") or ""),
                str(item.get("content") or ""),
                str(item.get("url") or ""),
            ]
            for u in item_meta.get("urls") or []:
                if isinstance(u, dict):
                    url_texts.extend(
                        [
                            str(u.get("expanded_url") or ""),
                            str(u.get("display_url") or ""),
                            str(u.get("short_url") or ""),
                        ]
                    )
                elif isinstance(u, str):
                    url_texts.append(u)

            for article_url in extract_article_urls(" ".join(url_texts)):
                article_map.setdefault(article_url, []).append(idx)

        if not article_map:
            return contents

        target_urls = list(article_map.keys())[:article_limit]
        text_map = await self._fetch_article_texts_with_playwright(
            target_urls, self.get_runtime_cookies(source)
        )

        for article_url, indexes in article_map.items():
            article_text = text_map.get(article_url)
            for idx in indexes:
                item = contents[idx]
                item_meta = item.get("metadata") or {}
                item_meta["article_url"] = article_url
                item_meta["article_fulltext"] = bool(article_text)
                item["metadata"] = item_meta
                if not article_text:
                    continue

                item_meta["article_text_chars"] = len(article_text)
                item["content"] = article_text
                item["url"] = article_url
                title = str(item.get("title") or "")
                if title_looks_like_url(title):
                    item["title"] = build_title_from_text(article_text)
        return contents

    async def _fetch_article_texts_with_playwright(
        self, article_urls: List[str], cookies: Dict[str, str]
    ) -> Dict[str, str]:
        if not article_urls:
            return {}

        from app.features import x_playwright_enabled

        if not x_playwright_enabled():
            # Default-off per audit 2026-04-20 S5: X article hydration via
            # logged-in Chromium touches ToS grey area. Skip quietly and let
            # the RSSHub / Nitter / API fallbacks deliver whatever text they
            # have. Operators can opt in with PIM_FEATURE_X_PLAYWRIGHT=true.
            self.logger.debug(
                "Skipping X article Playwright hydration (PIM_FEATURE_X_PLAYWRIGHT is off)"
            )
            return {}

        try:
            from app.utils.browser import get_browser_context
        except ImportError as exc:
            self.logger.warning(f"Playwright utilities unavailable for X article hydration: {exc}")
            return {}

        text_map: Dict[str, str] = {}
        x_ua = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        try:
            async with get_browser_context(headless=True, user_agent=x_ua) as context:
                cookie_items = build_x_cookie_items(cookies)
                if cookie_items:
                    await context.add_cookies(cookie_items)
                for article_url in article_urls:
                    page = await context.new_page()
                    try:
                        await page.goto(article_url, wait_until="domcontentloaded", timeout=30000)
                        await page.wait_for_timeout(4000)
                        raw = await page.evaluate(
                            """() => {
                                const articleNode = document.querySelector('article');
                                const mainNode = document.querySelector('main');
                                const articleText = articleNode && articleNode.innerText ? articleNode.innerText : '';
                                const mainText = mainNode && mainNode.innerText ? mainNode.innerText : '';
                                const bodyText = document.body && document.body.innerText ? document.body.innerText : '';
                                const candidates = [articleText, mainText, bodyText]
                                  .map((t) => (t || '').trim())
                                  .filter((t) => t.length > 0)
                                  .sort((a, b) => b.length - a.length);
                                return candidates[0] || '';
                            }"""
                        )
                        cleaned = clean_article_text(raw)
                        if cleaned:
                            text_map[article_url] = cleaned
                            self.logger.info(f"Hydrated X article text: {article_url} ({len(cleaned)} chars)")
                        else:
                            self.logger.info(f"X article text unavailable (likely auth-gated): {article_url}")
                    except Exception as exc:  # noqa: BLE001 - Playwright page errors vary widely
                        self.logger.warning(f"Failed to hydrate X article {article_url}: {exc}")
                    finally:
                        await page.close()
        except Exception as exc:  # noqa: BLE001 - broad Playwright / runtime surface
            self.logger.warning(f"Playwright article hydration failed: {exc}")
        return text_map
