"""Main content processor that orchestrates all processing steps."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional
from urllib.parse import urlparse

import aiohttp

from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.datetime import utcnow_naive
from app.features import KEYWORD_MONITORING_ENABLED
from app.models import Content, Keyword, Source
from app.processors.summarizer import Summarizer
from app.processors.translator import Translator
from app.processors.extractor import ContentExtractor
from app.processors.keyword_matcher import KeywordMatcher
from app.services.content_quality_service import merge_content_quality_metadata
from app.utils.cookies import normalize_cookie_dict
from app.utils.http import permissive_session_kwargs
from app.utils.logger import get_logger
from app.utils.ssrf import check_before_fetch
from app.utils.text import strip_html_tags, truncate_content

logger = get_logger(__name__)


@dataclass(frozen=True)
class ContentTypeStrategy:
    """Per-``content_type`` knobs used during processing.

    Extracted into a small registry (audit 2026-04-20 §8.2) so that
    ``ContentProcessor.process`` stays branch-free on source type, and
    adding a new type is a one-line edit to :data:`_CONTENT_TYPE_STRATEGIES`.
    """

    #: Extractive summary character budget (upper bound).
    summary_char_limit: int = 500
    #: When true, website-style cookie full-text fallback is attempted
    #: whenever the source carries runtime cookies.
    wants_cookie_fulltext: bool = False


_CONTENT_TYPE_STRATEGIES: Mapping[str, ContentTypeStrategy] = {
    "website": ContentTypeStrategy(summary_char_limit=500, wants_cookie_fulltext=True),
    "rss": ContentTypeStrategy(summary_char_limit=500),
    "x": ContentTypeStrategy(summary_char_limit=500),
    "youtube": ContentTypeStrategy(summary_char_limit=300),
    "podcast": ContentTypeStrategy(summary_char_limit=500),
}

_DEFAULT_STRATEGY = ContentTypeStrategy()


def strategy_for(content_type: str) -> ContentTypeStrategy:
    """Look up the strategy for ``content_type``; unknown types fall back to defaults."""
    return _CONTENT_TYPE_STRATEGIES.get(content_type, _DEFAULT_STRATEGY)


class ContentProcessor:
    """Process raw content through local extraction/cleanup and keyword matching."""
    
    def __init__(self):
        self.summarizer = Summarizer()
        self.translator = Translator()
        self.extractor = ContentExtractor()
        self.keyword_matcher = KeywordMatcher()

    def _get_runtime_cookies(self, source: Source) -> Dict[str, str]:
        """Resolve runtime cookies injected by fetch task."""
        auth = getattr(source, "_runtime_auth", None)
        if not isinstance(auth, dict):
            return {}
        credentials = auth.get("credentials", {}) if isinstance(auth.get("credentials"), dict) else {}
        return normalize_cookie_dict(credentials.get("cookies"))

    @staticmethod
    def _is_wrapper_url(url: str) -> bool:
        """Skip wrapper URLs that are not first-party article pages."""
        try:
            parsed = urlparse(url)
            host = (parsed.hostname or "").lower()
            path = parsed.path or ""
            return host == "news.google.com" and "/rss/articles/" in path
        except Exception:
            return False

    async def _fetch_full_text_with_cookies(
        self, url: str, cookies: Dict[str, str], source_url: str = "",
    ) -> Optional[str]:
        """Fetch first-party article page with cookies and extract readable text."""
        if not url or not cookies or self._is_wrapper_url(url):
            return None

        try:
            await check_before_fetch(url, source_url=source_url, cookies=cookies)
        except ValueError as exc:
            logger.warning("SSRF/cookie check blocked cookie fetch for %s: %s", url, exc)
            return None

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        try:
            cookie_jar = aiohttp.CookieJar()
            url_obj = aiohttp.client_reqrep.URL(url)
            for key, value in cookies.items():
                if not key or value is None:
                    continue
                cookie_jar.update_cookies({str(key): str(value)}, response_url=url_obj)

            async with aiohttp.ClientSession(
                **permissive_session_kwargs(cookie_jar=cookie_jar)
            ) as session:
                async with session.get(
                    url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=20),
                    allow_redirects=True,
                ) as response:
                    if response.status != 200:
                        return None
                    html = await response.text()

            extracted = await self.extractor.extract(html, url)
            clean = strip_html_tags(extracted or "")
            return clean if len(clean) >= 120 else None
        except Exception as e:
            logger.warning(f"Cookie full-text fetch failed for {url}: {e}")
            return None
    
    async def process(
        self,
        raw_content: Dict[str, Any],
        source: Source,
        keywords: Optional[List[Keyword]] = None,
        generate_summary: bool = True,
        translate: bool = True
    ) -> Content:
        """
        Process raw content and create a Content model instance.

        This path intentionally avoids LLM calls so high-concurrency fetch
        throughput is not blocked by model latency.
        """
        logger.info(f"Processing content: {raw_content.get('title', 'Untitled')[:50]}")
        
        # Extract main content if HTML is provided
        main_text = raw_content.get("content", "")
        html = raw_content.get("html")
        source_type = source.type.value if hasattr(source.type, "value") else str(source.type)
        strategy = strategy_for(source_type)
        runtime_cookies = self._get_runtime_cookies(source)
        cookie_fulltext_required = strategy.wants_cookie_fulltext and bool(runtime_cookies)
        
        if html and not main_text:
            main_text = await self.extractor.extract(html, raw_content.get("url"))
        
        # Strip HTML tags from main_text first
        main_text_clean = strip_html_tags(main_text) if main_text else ""

        # Any cookie-protected website source must attempt full-text retrieval.
        article_url = str(raw_content.get("url") or "")
        if cookie_fulltext_required and (not main_text_clean or len(main_text_clean) < 600):
            fetched_full_text = await self._fetch_full_text_with_cookies(
                article_url, runtime_cookies, source_url=source.url,
            )
            if fetched_full_text and len(fetched_full_text) > len(main_text_clean):
                main_text = fetched_full_text
                main_text_clean = fetched_full_text
        
        # Keep fetch path LLM-free: use extractive summary only.
        _ = generate_summary
        _ = translate
        summary = None
        if main_text_clean and len(main_text_clean) >= 50:
            limit = strategy.summary_char_limit
            summary = main_text_clean[:limit] + ("..." if len(main_text_clean) > limit else "")
            summary = strip_html_tags(summary)

        title = raw_content.get("title", "Untitled")
        title = strip_html_tags(title)
        translated_title = None
        translated_summary = None
        
        # Match keywords
        keyword_matches = []
        if KEYWORD_MONITORING_ENABLED and keywords:
            keyword_matches = self.keyword_matcher.match(
                title,
                main_text_clean,
                keywords,
            )
        
        # Parse publish time
        publish_time = raw_content.get("publish_time")
        if isinstance(publish_time, str):
            try:
                publish_time = datetime.fromisoformat(publish_time.replace("Z", "+00:00"))
            except Exception:
                publish_time = utcnow_naive()
        elif not publish_time:
            publish_time = utcnow_naive()
        
        # Create Content instance
        metadata = raw_content.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        if cookie_fulltext_required:
            metadata["cookie_fulltext_required"] = True
            metadata["cookie_fulltext_obtained"] = bool(main_text_clean and len(main_text_clean) >= 120)
            metadata["cookie_fulltext_length"] = len(main_text_clean or "")
        metadata = merge_content_quality_metadata(
            metadata,
            title=title,
            full_content=main_text_clean,
            summary=summary,
            translated_summary=translated_summary,
        )

        content = Content(
            source_id=source.id,
            external_id=raw_content.get("external_id"),
            title=title,
            translated_title=translated_title,
            summary=summary,
            translated_summary=translated_summary,
            original_url=raw_content.get("url", ""),
            content_type=source_type,
            publish_time=publish_time,
            full_content=truncate_content(main_text_clean, url=article_url) if main_text_clean else None,
            metadata_=metadata,
            keyword_matches=keyword_matches,
            fetched_at=utcnow_naive()
        )
        
        logger.info(f"Processed content: {content.title[:50]}...")
        return content
    
    async def process_batch(
        self,
        raw_contents: List[Dict[str, Any]],
        source: Source,
        keywords: Optional[List[Keyword]] = None,
        db: Optional[AsyncSession] = None
    ) -> List[Content]:
        """
        Process a batch of raw contents.
        
        Args:
            raw_contents: List of raw content dictionaries
            source: Source model instance
            keywords: Optional list of keywords to match
            db: Optional database session to save contents
        
        Returns:
            List of processed Content instances
        """
        contents = []
        
        for raw_content in raw_contents:
            try:
                content = await self.process(raw_content, source, keywords)
                contents.append(content)
                
                if db:
                    db.add(content)
                    
            except Exception as e:
                logger.error(f"Error processing content: {e}")
                continue
        
        if db and contents:
            try:
                await db.commit()
                logger.info(f"Saved {len(contents)} contents to database")
            except Exception as e:
                await db.rollback()
                logger.error(f"Batch commit failed, rolled back transaction: {e}")
                raise
        
        return contents
    
    async def reprocess_content(
        self,
        content: Content,
        regenerate_summary: bool = False,
        retranslate: bool = False
    ) -> Content:
        """
        Reprocess an existing content item.
        
        Args:
            content: Existing Content model instance
            regenerate_summary: Whether to regenerate the summary
            retranslate: Whether to retranslate
        
        Returns:
            Updated Content instance
        """
        if regenerate_summary and content.full_content:
            content.summary = await self.summarizer.summarize(content.full_content)

        if retranslate:
            if content.title and not self.translator.is_chinese(content.title):
                content.translated_title = await self.translator.translate(
                    content.title, "zh-CN"
                )
            if content.summary and not self.translator.is_chinese(content.summary):
                content.translated_summary = await self.translator.translate(
                    content.summary, "zh-CN"
                )

        content.metadata_ = merge_content_quality_metadata(
            content.metadata_ or {},
            title=content.title or "",
            full_content=content.full_content,
            summary=content.summary,
            translated_summary=content.translated_summary,
        )
        content.updated_at = utcnow_naive()
        return content
