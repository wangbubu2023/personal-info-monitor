"""X (Twitter) probe strategy (standalone, no mixin)."""

from __future__ import annotations

import re
from typing import Any, Optional

import feedparser

from app.services.probe_strategies.result import ProbeResult
from app.utils.logger import get_logger

logger = get_logger(__name__)


class XProbeStrategy:
    def __init__(self, helpers: Any):
        self.helpers = helpers

    async def probe(self, url: str) -> ProbeResult:
        username = self.extract_username(url)
        if not username:
            return ProbeResult(status="error", message=f"无法从 URL 中提取用户名: {url}")

        from app.config import get_settings
        settings = get_settings()

        auth_token = getattr(settings, "x_auth_token", None)
        ct0_token = getattr(settings, "x_ct0_token", None)
        if auth_token and ct0_token:
            try:
                from twikit import Client as TwikitClient
                client = TwikitClient("en-US")
                client.set_cookies({"auth_token": auth_token, "ct0": ct0_token})
                user = await client.get_user_by_screen_name(username)
                if user:
                    return ProbeResult(
                        status="ok", strategy="graphql",
                        message=f"GraphQL 可用，@{username} 已验证 (user_id={user.id})",
                        sample_count=0,
                    )
            except ImportError:
                logger.warning("twikit 未安装，跳过 GraphQL 探测")
            except Exception as exc:  # noqa: BLE001 - twikit raises mixed errors
                logger.warning(f"GraphQL 探测 @{username} 失败: {exc}")

        rsshub_url = getattr(settings, "rsshub_url", "https://rsshub.app")
        feed_url = f"{rsshub_url}/twitter/user/{username}"
        text = await self.helpers._http_get(feed_url, timeout=20)
        if text:
            feed = feedparser.parse(text)
            if feed.entries:
                return ProbeResult(
                    status="ok", strategy="rsshub", rss_url=feed_url,
                    message=f"RSSHub 可用，@{username} 有 {len(feed.entries)} 条推文",
                    sample_count=len(feed.entries),
                )

        raw_nitter = getattr(settings, "nitter_instances", None) or ""
        if raw_nitter:
            nitter_instances = [u.strip().rstrip("/") for u in raw_nitter.split(",") if u.strip()]
        else:
            nitter_instances = [
                "https://nitter.privacydev.net",
                "https://nitter.poast.org",
                "https://nitter.woodland.cafe",
            ]
        for inst in nitter_instances:
            nitter_feed = f"{inst}/{username}/rss"
            text = await self.helpers._http_get(nitter_feed, timeout=10)
            if text:
                feed = feedparser.parse(text)
                if feed.entries:
                    return ProbeResult(
                        status="ok", strategy="nitter", rss_url=nitter_feed,
                        message=f"Nitter 可用，@{username} 有 {len(feed.entries)} 条推文",
                        sample_count=len(feed.entries),
                    )

        bearer = getattr(settings, "x_bearer_token", None)
        if bearer and bearer not in ("", "xxx"):
            return ProbeResult(
                status="warning", strategy="api",
                message="RSSHub/Nitter 均不可用，将使用官方 API（需 Bearer Token）",
            )

        if not (auth_token and ct0_token):
            return ProbeResult(
                status="error", strategy="none",
                message=f"@{username} 无法抓取：未配置 X_AUTH_TOKEN/X_CT0_TOKEN，且 RSSHub/Nitter 不可用",
            )
        return ProbeResult(
            status="error", strategy="none",
            message=f"@{username} 无法抓取：所有策略均失败",
        )

    def extract_username(self, url: str) -> Optional[str]:
        if url.startswith("@"):
            return url[1:]
        match = re.search(r"(?:twitter\.com|x\.com)/(@)?([a-zA-Z0-9_]+)", url)
        if match:
            return match.group(2)
        if re.match(r"^[a-zA-Z0-9_]+$", url):
            return url
        return None
