"""Text normalization helpers."""

import logging
import re

logger = logging.getLogger(__name__)

MAX_FULL_CONTENT_LENGTH = 50_000


def truncate_content(text: str, url: str = "") -> str:
    """Truncate text to MAX_FULL_CONTENT_LENGTH, logging if truncation occurs."""
    if not text:
        return text
    if len(text) > MAX_FULL_CONTENT_LENGTH:
        logger.warning(
            "Content truncated from %d to %d chars: %s",
            len(text),
            MAX_FULL_CONTENT_LENGTH,
            url[:100],
        )
        return text[:MAX_FULL_CONTENT_LENGTH]
    return text


def strip_html_tags(text: str) -> str:
    """Remove HTML tags and normalize whitespace/entities."""
    if not text:
        return text
    clean = re.sub(r"<[^>]+>", "", text)
    clean = re.sub(r"\s+", " ", clean)
    clean = clean.replace("&nbsp;", " ")
    clean = clean.replace("&amp;", "&")
    clean = clean.replace("&lt;", "<")
    clean = clean.replace("&gt;", ">")
    clean = clean.replace("&quot;", '"')
    clean = clean.replace("&#39;", "'")
    clean = clean.replace("&hellip;", "...")
    return clean.strip()
