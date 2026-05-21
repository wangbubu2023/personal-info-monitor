"""Strip feed/listing boilerplate from summaries before scoring or display.

RSS and listing pages often prepend newsletter signup copy (e.g. The Verge
*Regulator* intro) or append paywall stubs. Those strings are not article
body and should not influence rule-based scoring.
"""

from __future__ import annotations

import re

from app.utils.text import strip_html_tags

_BOILERPLATE_MARKERS: tuple[str, ...] = (
    "hello and welcome to",
    "if you're not a subscriber",
    "if you are not a subscriber",
    "sign up for our",
    "send 'em over to",
    "send them over to",
    "a quick note:",
    "on hiatus for the next",
    "read the full story at",
    "read more at",
    "您好，欢迎来到",
    "欢迎来到《",
    "为verge订阅者准备的通讯",
    "订阅用户",
    "请立即注册",
    "发送邮件至",
    "温馨提示：",
    "newsletter for verge subscribers",
    "fine editorial enterprise",
)

_PAYWALL_TAIL = re.compile(
    r"(?:Read the full story at[^.]*\.?\s*|Read more at[^.]*\.?\s*"
    r"|在 The Verge 阅读全文。?\s*|阅读完整(?:报道|故事)[^。]*。?\s*)$",
    re.IGNORECASE,
)


def _sentence_is_boilerplate(sentence: str) -> bool:
    lowered = (sentence or "").strip().lower()
    if not lowered:
        return True
    return any(marker in lowered for marker in _BOILERPLATE_MARKERS)


def _split_sentences(text: str) -> list[str]:
    chunks = re.split(r"(?<=[.!?。！？])\s+|\n+", text)
    out: list[str] = []
    for chunk in chunks:
        piece = chunk.strip()
        if not piece:
            continue
        out.append(piece)
    return out


def _sentence_is_substantive(sentence: str) -> bool:
    text = (sentence or "").strip()
    if len(text) < 20:
        return False
    if not re.search(r"[\u4e00-\u9fff]", text) and len(text.split()) < 4:
        return False
    return True


def clean_listing_summary(text: str | None) -> str:
    """Remove newsletter/paywall boilerplate; return stripped summary text."""
    cleaned = strip_html_tags(text or "").strip()
    if not cleaned:
        return ""

    kept = [
        s
        for s in _split_sentences(cleaned)
        if not _sentence_is_boilerplate(s) and _sentence_is_substantive(s)
    ]
    cleaned = " ".join(kept).strip()
    cleaned = _PAYWALL_TAIL.sub("", cleaned).strip()
    return cleaned


def apply_summary_cleaning(content) -> bool:
    """Clean ``summary`` / ``translated_summary`` on a Content row in-place.

    Returns True when either field was modified.
    """
    changed = False
    for field in ("translated_summary", "summary"):
        raw = getattr(content, field, None)
        if not raw:
            continue
        cleaned = clean_listing_summary(raw)
        normalized_raw = strip_html_tags(raw).strip()
        if cleaned != normalized_raw:
            setattr(content, field, cleaned or None)
            changed = True
    return changed


__all__ = ["clean_listing_summary", "apply_summary_cleaning"]
