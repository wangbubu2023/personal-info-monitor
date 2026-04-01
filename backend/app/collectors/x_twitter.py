"""X (Twitter) content collector with split strategy helpers."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.collectors.base import BaseCollector
from app.collectors.x_twitter_articles import XCollectorArticleMixin
from app.collectors.x_twitter_feed import XCollectorFeedMixin
from app.collectors.x_twitter_graphql import XCollectorGraphQLMixin
from app.models import Source


class XCollector(
    XCollectorGraphQLMixin,
    XCollectorFeedMixin,
    XCollectorArticleMixin,
    BaseCollector,
):
    """Collector for X (Twitter) accounts using multiple fallback strategies."""

    DEFAULT_NITTER_INSTANCES = [
        "https://nitter.privacydev.net",
        "https://nitter.poast.org",
        "https://nitter.woodland.cafe",
    ]
    ARTICLE_URL_RE = re.compile(r"(?:https?://)?(?:x\.com|twitter\.com)/i/article/\d+", re.IGNORECASE)

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
            except Exception as e:
                self.logger.warning(f"Strategy '{strategy_name}' failed: {e}")

        self.logger.error(f"All strategies exhausted for @{username}")
        return []
