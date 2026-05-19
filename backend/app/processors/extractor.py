"""Content extraction from HTML."""

from typing import Optional

from app.pipeline.utils import _word_count
from app.utils.logger import get_logger
from app.utils.text import strip_html_tags

logger = get_logger(__name__)


def _remove_noise_elements(soup) -> None:
    """Drop obvious non-content nodes before text extraction."""
    for element in soup.find_all([
        "script", "style", "nav", "header", "footer",
        "aside", "form", "iframe", "noscript"
    ]):
        element.decompose()

    for class_name in ["sidebar", "navigation", "menu", "ad", "advertisement", "comment"]:
        # Bind `class_name` into the lambda's default args so each predicate
        # captures its own value instead of closing over the loop variable.
        for element in soup.find_all(class_=lambda x, needle=class_name: x and needle in x.lower()):
            element.decompose()


def _find_main_content(soup):
    return (
        soup.find("article") or
        soup.find("main") or
        soup.find(class_=lambda x: x and "content" in x.lower()) or
        soup.find(id=lambda x: x and "content" in x.lower()) or
        soup.body
    )


def _extract_metadata_from_meta_tags(soup) -> dict:
    metadata = {}
    for meta in soup.find_all("meta"):
        name = meta.get("name", "").lower() or meta.get("property", "").lower()
        content = meta.get("content")
        if not name or not content:
            continue
        if name in ["description", "og:description", "twitter:description"]:
            metadata["description"] = content
        elif name in ["author", "article:author"]:
            metadata["author"] = content
        elif name in ["keywords"]:
            metadata["keywords"] = [k.strip() for k in content.split(",")]
        elif name in ["og:image", "twitter:image"]:
            metadata["image"] = content
        elif name in ["article:published_time", "date"]:
            metadata["published_time"] = content
    return metadata


class ContentExtractor:
    """Extract main content from HTML pages."""
    
    async def extract(self, html: str, url: Optional[str] = None) -> str:
        """
        Extract main content from HTML.
        
        Args:
            html: Raw HTML content
            url: Optional URL for context
        
        Returns:
            Extracted markdown or plain text content
        """
        if not html:
            return ""
        
        # 1. Try Readability LXML (best for structure preservation)
        content = self._extract_with_readability(html)
        
        # 2. Try trafilatura if readability failed or was too sparse
        if not content or len(content) < 200:
            trafil_content = self._extract_with_trafilatura(html, url)
            if trafil_content and len(trafil_content) > len(content or ""):
                content = trafil_content
        
        # 3. Fall back to BeautifulSoup if still nothing significant
        if not content or len(content) < 100:
            content = self._extract_with_beautifulsoup(html)
        
        return content

    def _extract_with_readability(self, html: str) -> str:
        """Extract content using readability-lxml and convert to markdown."""
        try:
            from readability import Document
            import markdownify
            
            doc = Document(html)
            summary_html = doc.summary()
            
            if not summary_html or len(summary_html) < 100:
                return ""
                
            # Convert to high-quality markdown
            # markdownify 0.14+ doesn't allow both strip and convert. 
            # We use 'convert' to define the allowlist.
            md = markdownify.markdownify(
                summary_html,
                heading_style="ATX",
                bullets="-",
                convert=["table", "tr", "td", "th", "img", "a", "p", "br", "strong", "em", "code", "pre", "h1", "h2", "h3", "h4", "h5", "h6"]
            )
            
            if md:
                logger.debug(f"Extracted {len(md)} chars with Readability+Markdownify")
            
            # RUTHLESS: If content is too thin after cleaning, it's noise or a stub.
            # We return empty string to trigger pipeline rejection.
            text_only = strip_html_tags(summary_html)
            
            # LINK DENSITY CHECK: Navigation pages have high link text ratio.
            link_density = self._calculate_link_density(summary_html)
            if link_density > 0.45 and len(text_only) < 1000:
                logger.debug(f"Readability: High link density ({link_density:.2f}), treating as navigation hub")
                return ""

            if len(text_only) < 250 and _word_count(text_only) < 40:
                logger.debug(f"Readability: Content too thin ({len(text_only)} chars), treating as noise")
                return ""
                
            return md.strip()
        except Exception as e:
            logger.error(f"Readability extraction failed: {e}")
            return ""

    def _calculate_link_density(self, html: str) -> float:
        """Calculate ratio of link text to total text."""
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "lxml")
            total_text = strip_html_tags(html)
            if not total_text.strip():
                return 0.0
            
            link_text = ""
            for a in soup.find_all("a"):
                link_text += a.get_text(strip=True)
                
            density = len(link_text) / len(total_text)
            return density
        except Exception:
            return 0.0
    
    def _extract_with_trafilatura(
        self,
        html: str,
        url: Optional[str] = None
    ) -> str:
        """Extract content using trafilatura."""
        try:
            import trafilatura
            
            content = trafilatura.extract(
                html,
                url=url,
                include_comments=False,
                include_tables=True,
                no_fallback=False
            )
            
            if content:
                logger.debug(f"Extracted {len(content)} chars with trafilatura")
                return content
            
            return ""
            
        except Exception as e:
            logger.error(f"Trafilatura extraction error: {e}")
            return ""
    
    def _extract_with_beautifulsoup(self, html: str) -> str:
        """Extract content using BeautifulSoup."""
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "lxml")
            _remove_noise_elements(soup)

            main_content = _find_main_content(soup)
            if not main_content:
                return ""

            text = main_content.get_text(separator="\n", strip=True)

            import re
            text = re.sub(r'\n{3,}', '\n\n', text)

            logger.debug(f"Extracted {len(text)} chars with BeautifulSoup")
            return text

        except Exception as e:
            logger.error(f"BeautifulSoup extraction error: {e}")
            return ""
    
    def extract_metadata(self, html: str) -> dict:
        """Extract metadata from HTML (title, author, date, etc.)."""
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "lxml")
            metadata = {}

            # Title from <title> tag
            if soup.title and soup.title.string:
                metadata["title"] = soup.title.string.strip()

            # Metadata from <meta> tags (og:title overrides if present)
            metadata.update(_extract_metadata_from_meta_tags(soup))

            # og:title / twitter:title override plain title
            for meta in soup.find_all("meta"):
                prop = (meta.get("property") or meta.get("name") or "").lower()
                if prop in ("og:title", "twitter:title"):
                    content = meta.get("content")
                    if content:
                        metadata["title"] = content.strip()

            # Last-resort: first <h1>
            if not metadata.get("title"):
                h1 = soup.find("h1")
                if h1:
                    metadata["title"] = h1.get_text(strip=True)

            return metadata

        except Exception as e:
            logger.error(f"Metadata extraction error: {e}")
            return {}
