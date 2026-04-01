"""Content extraction from HTML."""

from typing import Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


def _remove_noise_elements(soup) -> None:
    """Drop obvious non-content nodes before text extraction."""
    for element in soup.find_all([
        "script", "style", "nav", "header", "footer",
        "aside", "form", "iframe", "noscript"
    ]):
        element.decompose()

    for class_name in ["sidebar", "navigation", "menu", "ad", "advertisement", "comment"]:
        for element in soup.find_all(class_=lambda x: x and class_name in x.lower()):
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
            Extracted plain text content
        """
        if not html:
            return ""
        
        # Try trafilatura first (best for article extraction)
        content = self._extract_with_trafilatura(html, url)
        
        if not content or len(content) < 100:
            # Fall back to BeautifulSoup
            content = self._extract_with_beautifulsoup(html)
        
        return content
    
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
        """Extract metadata from HTML (title, description, etc.)."""
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "lxml")

            metadata = {}
            if soup.title:
                metadata["title"] = soup.title.string

            metadata.update(_extract_metadata_from_meta_tags(soup))
            return metadata

        except Exception as e:
            logger.error(f"Metadata extraction error: {e}")
            return {}
