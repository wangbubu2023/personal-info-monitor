"""Text normalization helpers."""

import logging
import re

logger = logging.getLogger(__name__)

# Embedded image / binary accidentally stored as text (e.g. RSS description = raw PNG).
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC_PREFIX = b"\xff\xd8\xff"
_GIF_MAGIC = (b"GIF87a", b"GIF89a")
_WEBP_MAGIC = b"RIFF"


def text_looks_like_embedded_binary(s: str) -> bool:
    """True when *s* likely contains raw image/binary bytes mis-decoded as text."""
    if not s or not str(s).strip():
        return False
    raw = str(s).strip()
    b_utf = raw.encode("utf-8", errors="surrogatepass")
    if _PNG_MAGIC in b_utf[:512] or b_utf.startswith(_JPEG_MAGIC_PREFIX):
        return True
    if b_utf[:4] == _WEBP_MAGIC and b"WEBP" in b_utf[:16]:
        return True
    for gif in _GIF_MAGIC:
        if b_utf.startswith(gif):
            return True

    # Latin-1 roundtrip catches \x89PNG in mixed encodings
    try:
        latin = raw.encode("latin-1", errors="ignore")
        if _PNG_MAGIC in latin[:512] or latin.startswith(_JPEG_MAGIC_PREFIX):
            return True
    except Exception:
        pass

    head = raw[:500]
    if "\x00" in head:
        return True

    # Mis-decoded PNG often shows "PNG" + IHDR in first window
    up = head.upper()
    if "IHDR" in up and "PNG" in up[:120]:
        return True

    # Many U+FFFD => binary decoded as UTF-8
    if len(raw) >= 24:
        repl = raw.count("\ufffd")
        if repl / len(raw) > 0.12:
            return True

    return False

MAX_FULL_CONTENT_LENGTH = 50_000

# Standalone embed / ad labels that often survive HTML extraction as their own
# "paragraph" (Engadget VIDEO, NYT 广告, etc.).
_ARTICLE_NOISE_LINE_RE = re.compile(
    r"^(?:"
    r"VIDEO|AUDIO|SLIDESHOW|GALLERY|PHOTOS|IMAGE|"
    r"Advertisement|Ads?|Sponsored|Recommended|Related|"
    r"广告|推荐阅读|延伸阅读|相关阅读"
    r")$",
    re.IGNORECASE,
)

_HTML_TEXT_BLOCK_TAGS = (
    "p",
    "li",
    "blockquote",
    "pre",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "div",
    "section",
    "article",
)


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


def html_to_text_preserving_blocks(html: str) -> str:
    """Convert HTML to plain text while preserving block-level paragraph breaks.

    Global ``get_text(separator="\n\n")`` over-splits inline tags, while
    ``separator="\n"`` flattens adjacent paragraphs for Markdown rendering.
    This extracts leaf block nodes, keeps inline text within each block, and
    joins blocks with blank lines.
    """
    if not html:
        return html
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(str(html), "lxml")
    except Exception:
        return strip_html_tags(html)

    for element in soup.find_all(["script", "style", "noscript", "template", "svg"]):
        element.decompose()

    blocks: list[str] = []
    for node in soup.find_all(_HTML_TEXT_BLOCK_TAGS):
        if node.find(_HTML_TEXT_BLOCK_TAGS):
            continue
        text = node.get_text(separator=" ", strip=True)
        text = re.sub(r"\s+", " ", text).strip()
        text = re.sub(r"\s+([，。！？；：、,.!?;:])", r"\1", text)
        if text:
            blocks.append(text)

    if not blocks:
        fallback = soup.get_text(separator=" ", strip=True)
        fallback = re.sub(r"\s+", " ", fallback).strip()
        return re.sub(r"\s+([，。！？；：、,.!?;:])", r"\1", fallback)
    return "\n\n".join(blocks).strip()


def strip_markdown(text: str) -> str:
    """Convert lightweight markdown to plain text for reader storage/display."""
    if not text:
        return text

    value = text.replace("\r\n", "\n")

    value = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"<(https?://[^>]+)>", r"\1", value)

    # Section labels like **Summary** at the start of a block.
    value = re.sub(r"(^|\n)\*\*([^*\n]+)\*\*(?=\s)", r"\1\2\n\n", value)
    value = re.sub(r"(^|\n)__([^_\n]+)__(?=\s)", r"\1\2\n\n", value)

    value = re.sub(r"\*\*([^*]+)\*\*", r"\1", value)
    value = re.sub(r"__([^_]+)__", r"\1", value)
    value = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", value)
    value = re.sub(r"(?<!_)_([^_\n]+)_(?!_)", r"\1", value)

    value = re.sub(r"^#{1,6}\s+", "", value, flags=re.MULTILINE)
    value = re.sub(r"`([^`]+)`", r"\1", value)
    value = re.sub(r"^[\-\*\+]\s+", "", value, flags=re.MULTILINE)
    value = re.sub(r"^\s*[-*_]{3,}\s*$", "", value, flags=re.MULTILINE)
    value = re.sub(r"\n{3,}", "\n\n", value)

    return value.strip()


def _normalize_article_line(line: str) -> str:
    return re.sub(r"[ \t]+", " ", strip_html_tags(line)).strip()


def _is_article_noise_line(line: str) -> bool:
    return bool(_ARTICLE_NOISE_LINE_RE.match(line))


def normalize_article_text(text: str) -> str:
    """Normalize extracted article text to plain, reader-friendly paragraphs."""
    if not text:
        return text

    cleaned = strip_markdown(text).replace("\r\n", "\n").strip()
    if not cleaned:
        return cleaned

    blocks = re.split(r"\n{2,}", cleaned)
    if len(blocks) <= 1:
        blocks = [line for line in cleaned.split("\n") if line.strip()]

    paragraphs: list[str] = []
    for block in blocks:
        lines: list[str] = []
        for line in block.split("\n"):
            normalized_line = _normalize_article_line(line)
            if normalized_line and not _is_article_noise_line(normalized_line):
                lines.append(normalized_line)
        if lines:
            paragraphs.append(" ".join(lines))

    return "\n\n".join(paragraphs).strip()
