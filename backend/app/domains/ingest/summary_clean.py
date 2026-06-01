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

# Boilerplate markers that show up specifically inside article *bodies*
# (full_content) of Chinese tech/finance media. These never carry atomizable
# facts: ad disclaimers, reprint notices, public-account attributions, author
# bios, and VC-service marketing copy.
ATOM_BOILERPLATE_MARKERS: tuple[str, ...] = (
    "广告声明：文内含有的对外跳转链接",
    "it之家所有文章均包含本声明",
    "聚焦全球优秀创业者，项目融资率",
    "一级市场金融信息和系统服务提供商",
    "推送和解读前沿、有料的科技创投资讯",
    "本文来自微信公众号",
    "原文标题",
    "封面来源",
    "未经允许不得转载",
    "本文为澎湃号作者",
    "声明：本文内容及配图由入驻作者撰写",
    "本文版权归作者所有",
    "本文系作者个人观点",
    "免责声明",
    "转载请注明出处",
    "点击下载",
    "扫码关注",
)

# Combined marker set used by atomization cleaning: listing boilerplate +
# article-body boilerplate.
_ATOM_CLEAN_MARKERS: tuple[str, ...] = _BOILERPLATE_MARKERS + ATOM_BOILERPLATE_MARKERS

# Fenced code blocks and HTML <pre>/<code> blocks rarely contain news facts and
# generate noisy candidate sentences (``Arguments:``, ``9 occurrences.``).
_CODE_FENCE_RE = re.compile(r"```[\s\S]*?```|~~~[\s\S]*?~~~", re.MULTILINE)
_HTML_CODE_BLOCK_RE = re.compile(r"<(pre|code)\b[^>]*>[\s\S]*?</\1>", re.IGNORECASE)

# Keep terminal punctuation with the preceding chunk so the rejoined text still
# splits cleanly downstream in ``sentence_split.split_sentences``.
_ATOM_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])\s*|\n+")


def text_hits_atom_boilerplate(text: str | None) -> bool:
    """True when *text* contains a known boilerplate / disclaimer / ad marker."""
    lowered = (text or "").strip().lower()
    if not lowered:
        return False
    return any(marker in lowered for marker in _ATOM_CLEAN_MARKERS)


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


def clean_for_atomization(text: str | None) -> str:
    """Coarse body-level cleaning before sentence splitting for atom extraction.

    Removes code blocks, HTML, and boilerplate/disclaimer lines while preserving
    sentence boundaries. Fine-grained per-sentence filtering (short fragments,
    code-like, label-like) happens later in ``sentence_quality_reason``.
    """
    raw = text or ""
    if not raw.strip():
        return ""

    raw = _HTML_CODE_BLOCK_RE.sub(" ", raw)
    raw = _CODE_FENCE_RE.sub(" ", raw)
    cleaned = strip_html_tags(raw).strip()
    if not cleaned:
        return ""

    kept: list[str] = []
    for chunk in _ATOM_SPLIT_RE.split(cleaned):
        sentence = (chunk or "").strip()
        if not sentence:
            continue
        if text_hits_atom_boilerplate(sentence):
            continue
        kept.append(sentence)

    result = " ".join(kept).strip()
    return _PAYWALL_TAIL.sub("", result).strip()


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


__all__ = [
    "ATOM_BOILERPLATE_MARKERS",
    "apply_summary_cleaning",
    "clean_for_atomization",
    "clean_listing_summary",
    "text_hits_atom_boilerplate",
]
