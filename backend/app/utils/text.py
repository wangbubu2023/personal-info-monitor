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
