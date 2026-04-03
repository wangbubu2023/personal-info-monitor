"""Website probe strategy mixin."""

from app.utils.logger import get_logger
from bs4 import BeautifulSoup
from app.services.probe_strategies.result import ProbeResult

logger = get_logger(__name__)

# Special sentinel values (must match rss.py)
_UNFETCHABLE = "__UNFETCHABLE__"
_USE_SCRAPING = "__SCRAPING__"


class WebsiteProbeStrategy:

    async def _probe_website(self, url: str):
        """Probe a website URL."""
        # 1. Check known RSS feeds first
        known = self._check_known_feeds(url)
        if known is not None:
            if known == _UNFETCHABLE:
                # Give site-specific messages
                if "facebook.com" in url:
                    msg = "Facebook 个人页面不支持 RSS 或网页抓取"
                elif "theinformation.com" in url:
                    msg = "The Information 为付费订阅站，Feed 需要认证，暂不支持免费抓取"
                else:
                    msg = "该平台不支持自动抓取"
                return ProbeResult(
                    status="error",
                    strategy="none",
                    message=msg,
                )
            if known == _USE_SCRAPING:
                # Skip RSS attempts, go directly to scraping
                scrape_result = await self._test_scrape(url)
                if scrape_result.sample_count > 0:
                    return scrape_result
                # If scraping also fails, continue to the normal flow
            else:
                # Test the known feed
                result = await self._test_rss_feed(known)
                if result.status == "ok":
                    return result

        # 2. Try to discover RSS feed from page
        rss_url = await self._discover_rss(url)
        if rss_url:
            result = await self._test_rss_feed(rss_url)
            if result.status == "ok":
                return result

        # 3. Try common RSS paths
        rss_url = await self._try_common_rss_paths(url)
        if rss_url:
            result = await self._test_rss_feed(rss_url)
            if result.status == "ok":
                return result

        # 4. Try static scraping
        scrape_result = await self._test_scrape(url)
        if scrape_result.status == "ok":
            return scrape_result

        # 5. Nothing worked
        return ProbeResult(
            status="error",
            strategy="none",
            message="无法通过 RSS 或网页抓取获取内容，可能需要 JS 渲染或该站有反爬保护",
        )

    async def _test_scrape(self, url: str):
        """Test if we can scrape articles from the page."""
        try:
            html = await self._http_get(url)
            if not html:
                return ProbeResult(status="error", strategy="scrape",
                                   message="网页无法访问")

            soup = BeautifulSoup(html, "html.parser")
            # Try to find article-like elements (covers both English & Chinese sites)
            selectors = [
                "article", ".post", ".entry", "main article",
                "[class*='article']", "[class*='post']", "[class*='story']",
                "[class*='news']", "[class*='item']", "[class*='card']",
                ".list-item", ".feed-item", ".content-item",
                "li[class]>a[href]",  # common list-based layouts
            ]
            articles = []
            for sel in selectors:
                try:
                    articles = soup.select(sel)
                except Exception as exc:
                    logger.debug("BS4 select failed: %s", exc)
                    continue
                if len(articles) >= 3:
                    break

            if not articles:
                # Try finding links with titles
                links = soup.select("a[href]")
                article_links = [
                    a for a in links
                    if a.get_text(strip=True)
                    and len(a.get_text(strip=True)) > 20
                    and a.get("href", "").startswith(("http", "/"))
                ]
                if len(article_links) >= 3:
                    return ProbeResult(
                        status="warning",
                        strategy="scrape",
                        message=f"未找到标准文章结构，但发现 {len(article_links)} 个链接可供提取",
                        sample_count=len(article_links),
                    )
                return ProbeResult(
                    status="error", strategy="scrape",
                    message="网页可访问但未找到可提取的文章内容，可能需要 JS 渲染",
                )

            return ProbeResult(
                status="ok" if len(articles) >= 3 else "warning",
                strategy="scrape",
                message=f"网页抓取可用，发现 {len(articles)} 篇文章",
                sample_count=len(articles),
            )
        except Exception as e:
            return ProbeResult(status="error", strategy="scrape",
                               message=f"网页抓取测试失败: {e}")
