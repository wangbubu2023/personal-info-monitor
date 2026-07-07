"""Shared reader helpers — pure functions for body cleaning, paragraph
splitting, title heuristics, and translation-validity gates.

Moved out of :mod:`app.api.content_shared` as part of Phase 4 step 1 of
the module-refactor blueprint. The HTTP layer (``app.api.contents``,
``app.api.contents_reader``) and the reader service modules
(``app.services.reader.{body_loader, streaming, translation}``) all
need these helpers; lifting them out of ``app.api`` was the one and
only way to eliminate the ``services → api`` reverse dependency the
blueprint called out (Phase 4 step 5 then relocated the reader
service modules themselves into this same sub-domain).

These functions are intentionally **pure-ish**: only :func:`_is_valid_translation_text`
and :func:`_is_valid_title_translation` touch the Translator (and only
for a Chinese-detect heuristic — no LLM call). Everything else is
regex / hashlib / html builders, safe to call from any layer.

The legacy ``app.api.content_shared`` path remains as a re-export
shim so consumers (and ``test_reader_split.py``'s direct imports
via ``from app.api.contents import _split_for_reader``) keep working
through Phase 7.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import html
import re
from typing import Any, Optional
from urllib.parse import urlparse

from app.platform.llm.translator import Translator
from app.utils.text import normalize_article_text
from app.utils.x_twitter_text import is_x_status_page_url as _is_x_status_page_url
from app.utils.x_twitter_text import looks_like_x_interstitial_text as _looks_like_x_interstitial_text

_X_ARTICLE_URL_RE = re.compile(r"(?:https?://)?(?:x\.com|twitter\.com)/i/article/\d+", re.IGNORECASE)
_TITLE_URL_RE = re.compile(r"^(?:https?://|www\.)", re.IGNORECASE)
_MARKDOWN_IMAGE_RE = re.compile(r"^!\[([^\]]*)\]\((https?://[^)\s]+)(?:\s+\"([^\"]*)\")?\)$")
_MARKDOWN_LINK_RE = re.compile(r"^\[([^\]]+)\]\((https?://[^)\s]+)\)$")
_BARE_HTTP_URL_RE = re.compile(r"^https?://[^\s<>()]+$")
_IMAGE_URL_RE = re.compile(r"\.(?:avif|gif|jpe?g|png|webp)(?:[?#].*)?$", re.IGNORECASE)
_CODE_FENCE_RE = re.compile(r"^```([A-Za-z0-9_+.-]{0,32})?\n?(.*?)\n?```$", re.DOTALL)
_FOOTNOTE_RE = re.compile(r"^(?:\[(\d{1,3})\]|\^(\d{1,3})|(\d{1,3})\.)\s+(.{8,})$", re.DOTALL)


def _title_looks_like_url(title: str) -> bool:
    text = (title or "").strip().lower()
    if not text:
        return True
    return bool(_TITLE_URL_RE.match(text)) or "t.co/" in text


def _looks_like_translation_refusal(text: str) -> bool:
    value = (text or "").strip().lower()
    if not value:
        return False
    markers = (
        "i cannot translate",
        "i can't translate",
        "please provide",
        "无法翻译",
        "请提供",
        "没有提供",
        "未提供",
        "无法进行翻译",
    )
    return any(marker in value for marker in markers)


def _reader_body_hash(text: str) -> str:
    normalized = (text or "").strip()
    if not normalized:
        return ""
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def _extract_x_article_url(metadata: dict) -> str:
    if not isinstance(metadata, dict):
        return ""

    direct = str(metadata.get("article_url") or "").strip()
    if direct:
        matched = _X_ARTICLE_URL_RE.search(direct)
        if matched:
            direct = matched.group(0).strip()
            if not direct.startswith("http://") and not direct.startswith("https://"):
                direct = f"https://{direct}"
            if direct.startswith("http://"):
                direct = "https://" + direct[len("http://"):]
            return direct

    for item in metadata.get("urls") or []:
        candidates: list[str] = []
        if isinstance(item, dict):
            candidates.extend(
                [
                    str(item.get("expanded_url") or ""),
                    str(item.get("display_url") or ""),
                    str(item.get("short_url") or ""),
                ]
            )
        elif isinstance(item, str):
            candidates.append(item)
        for candidate in candidates:
            matched = _X_ARTICLE_URL_RE.search(candidate or "")
            if not matched:
                continue
            url = matched.group(0).strip()
            if not url.startswith("http://") and not url.startswith("https://"):
                url = f"https://{url}"
            if url.startswith("http://"):
                url = "https://" + url[len("http://"):]
            return url
    return ""


def _is_valid_translation_text(text: Optional[str]) -> bool:
    if not text or not text.strip():
        return False
    return Translator().is_chinese(text)


def _is_valid_title_translation(original: str, candidate: Optional[str]) -> bool:
    if not _is_valid_translation_text(candidate):
        return False
    value = str(candidate).strip()
    if _looks_like_translation_refusal(value):
        return False
    if _title_looks_like_url(original):
        return False
    if len(value) > max(180, len(original) * 6):
        return False
    return True


def _split_for_reader(text: str) -> list[str]:
    """Split plain text into readable paragraphs."""
    cleaned = normalize_article_text(text or "").replace("\r\n", "\n").strip()
    if not cleaned:
        return []

    paragraphs = [p.strip() for p in re.split(r"\n{2,}", cleaned) if p.strip()]
    if len(paragraphs) <= 1:
        protected = re.sub(
            r"\b(?:[A-Za-z]\.){2,}",
            lambda m: m.group(0).replace(".", "<DOT>"),
            cleaned,
        )
        paragraphs = [
            p.replace("<DOT>", ".").strip()
            for p in re.split(r"(?<=[。！？.!?])\s+", protected)
            if p.strip()
        ]
    return paragraphs


def _safe_reader_url(value: Any) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 2048:
        return ""
    try:
        parsed = urlparse(text)
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return text


def _reader_text(value: Any, *, limit: int = 6000) -> str:
    text = str(value or "").replace("\r\n", "\n").strip()
    if not text:
        return ""
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:limit].strip()


def _reader_image_from_url(url: str, *, alt: str = "") -> dict[str, str] | None:
    safe_url = _safe_reader_url(url)
    if not safe_url:
        return None
    if not _IMAGE_URL_RE.search(safe_url):
        return None
    block: dict[str, str] = {"type": "image", "src": safe_url}
    clean_alt = _reader_text(alt, limit=240)
    if clean_alt:
        block["alt"] = clean_alt
    return block


def _reader_image_blocks_from_metadata(metadata: dict | None) -> list[dict[str, str]]:
    if not isinstance(metadata, dict):
        return []

    blocks: list[dict[str, str]] = []

    direct_image = _reader_image_from_url(str(metadata.get("image") or ""), alt=str(metadata.get("image_alt") or ""))
    if direct_image:
        blocks.append(direct_image)

    for raw in metadata.get("images") or []:
        image = _reader_image_from_url(str(raw or ""))
        if image:
            blocks.append(image)

    for item in [*(metadata.get("media") or []), *(metadata.get("enclosures") or [])]:
        if not isinstance(item, dict):
            continue
        media_type = str(item.get("type") or "").lower()
        if media_type and not media_type.startswith("image/"):
            continue
        image = _reader_image_from_url(str(item.get("url") or item.get("href") or ""))
        if image:
            blocks.append(image)

    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for block in blocks:
        src = block.get("src", "")
        if src and src not in seen:
            seen.add(src)
            unique.append(block)
    return unique[:3]


def _reader_block_from_paragraph(paragraph: str) -> dict[str, Any] | None:
    raw = (paragraph or "").strip()
    if not raw:
        return None

    code_match = _CODE_FENCE_RE.match(raw)
    if code_match:
        language = _reader_text(code_match.group(1), limit=32)
        code_text = _reader_text(code_match.group(2), limit=20000)
        if code_text:
            block: dict[str, Any] = {"type": "code", "text": code_text}
            if language:
                block["language"] = language
            return block

    image_match = _MARKDOWN_IMAGE_RE.match(raw)
    if image_match:
        image = _reader_image_from_url(image_match.group(2), alt=image_match.group(1))
        if image:
            caption = _reader_text(image_match.group(3), limit=240)
            if caption:
                image["caption"] = caption
            return image

    heading_match = re.match(r"^(#{1,4})\s+(.+)$", raw)
    if heading_match:
        text = _reader_text(heading_match.group(2), limit=240)
        if text:
            return {"type": "heading", "level": min(4, len(heading_match.group(1))), "text": text}

    footnote_match = _FOOTNOTE_RE.match(raw)
    if footnote_match:
        marker = footnote_match.group(1) or footnote_match.group(2) or footnote_match.group(3) or ""
        text = _reader_text(footnote_match.group(4), limit=6000)
        if text:
            return {"type": "footnote", "marker": marker, "text": text}

    quote_lines = []
    for line in raw.split("\n"):
        stripped = line.strip()
        if not stripped.startswith(">"):
            quote_lines = []
            break
        quote_lines.append(stripped.lstrip(">").strip())
    if quote_lines:
        text = _reader_text("\n".join(quote_lines), limit=6000)
        if text:
            return {"type": "quote", "text": text}

    link_match = _MARKDOWN_LINK_RE.match(raw)
    if link_match:
        href = _safe_reader_url(link_match.group(2))
        text = _reader_text(link_match.group(1), limit=240)
        if href and text:
            return {"type": "link", "href": href, "text": text}

    if _BARE_HTTP_URL_RE.match(raw):
        image = _reader_image_from_url(raw)
        if image:
            return image
        href = _safe_reader_url(raw)
        if href:
            return {"type": "link", "href": href, "text": href}

    text = _reader_text(normalize_article_text(raw), limit=20000)
    if not text:
        return None
    return {"type": "paragraph", "text": text}


def _build_reader_blocks(text: str, metadata: dict | None = None) -> list[dict[str, Any]]:
    """Build safe, typed reader blocks from text plus trusted content metadata.

    The frontend renders only these block types and never receives arbitrary
    HTML for direct insertion into the DOM.
    """
    raw = (text or "").replace("\r\n", "\n").strip()
    blocks: list[dict[str, Any]] = []

    blocks.extend(_reader_image_blocks_from_metadata(metadata))

    if raw:
        paragraphs = [p.strip() for p in re.split(r"\n{2,}", raw) if p.strip()]
        if len(paragraphs) <= 1:
            paragraphs = _split_for_reader(raw)
        for paragraph in paragraphs:
            block = _reader_block_from_paragraph(paragraph)
            if block:
                blocks.append(block)

    if not blocks:
        return []

    # Keep the response bounded; body_raw remains available for legacy callers.
    return blocks[:300]


def _derive_title_from_body(text: str) -> str:
    if not text:
        return ""

    skip_exact = {
        "查看键盘快捷键",
        "要查看键盘快捷键，按下问号",
        "Log in",
        "Sign up",
        "Articles",
        "Posts",
        "Replies",
        "·",
    }
    lines: list[str] = []
    for paragraph in _split_for_reader(text):
        for line in paragraph.split("\n"):
            candidate = (line or "").strip()
            if not candidate or candidate in skip_exact:
                continue
            if candidate.startswith("@"):
                continue
            if re.fullmatch(r"[·•\-\s]+", candidate):
                continue
            if re.fullmatch(r"\d+(?:\.\d+)?(?:万|亿|k|K|m|M|千)?", candidate):
                continue
            if re.fullmatch(r"\d+\s*(?:秒|分钟|小时|天|周|月|年)", candidate):
                continue
            if re.fullmatch(r"\d+月\d+日", candidate):
                continue
            if len(candidate) < 8:
                continue
            lines.append(candidate)
            if len(lines) >= 12:
                break
        if len(lines) >= 12:
            break

    if not lines:
        return ""
    title = lines[0][:120].strip()
    if len(lines[0]) > 120:
        title += "..."
    return title


def _clean_x_reader_body(text: str) -> str:
    cleaned = (text or "").replace("\r\n", "\n").strip()
    if not cleaned:
        return ""
    if _looks_like_x_interstitial_text(cleaned):
        return ""

    skip_exact = {
        "查看键盘快捷键",
        "要查看键盘快捷键，按下问号",
        "键盘快捷键",
        "键盘快捷方式",
        "Log in",
        "Sign up",
        "Posts",
        "Replies",
        "Articles",
        "Media",
        "·",
    }
    filtered: list[str] = []
    for line in [line.strip() for line in cleaned.split("\n") if line.strip()]:
        if line in skip_exact or line.startswith("@"):
            continue
        if re.fullmatch(r"[·•\-\s]+", line):
            continue
        if re.fullmatch(r"\d+(?:\.\d+)?(?:万|亿|k|K|m|M|千)?", line):
            continue
        if re.fullmatch(r"\d+\s*(?:秒|分钟|小时|天|周|月|年)", line):
            continue
        if re.fullmatch(r"\d+月\d+日", line):
            continue
        filtered.append(line)
    result = "\n".join(filtered).strip()
    return result if len(result) >= 280 else cleaned


def _build_clean_reader_html(
    title: str,
    source_name: str,
    original_url: str,
    publish_time: Optional[datetime],
    body_zh: str,
) -> str:
    """Build a sanitized, reader-friendly HTML document."""
    publish_text = publish_time.isoformat() if publish_time else "-"
    body_html = "\n".join(f"<p>{html.escape(p)}</p>" for p in _split_for_reader(body_zh))
    if not body_html:
        body_html = "<p>暂无可阅读正文。</p>"

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(title or "内容阅读")}</title>
  <style>
    body {{ max-width: 920px; margin: 24px auto; padding: 0 18px; line-height: 1.9; color: #1f1f1f; font-family: -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif; }}
    h1 {{ font-size: 28px; margin: 0 0 8px; line-height: 1.4; }}
    .meta {{ color: #6b7280; font-size: 13px; margin-bottom: 20px; }}
    .meta a {{ color: #6b7c3f; text-decoration: none; }}
    .meta a:hover {{ text-decoration: underline; }}
    article p {{ margin: 0 0 14px; white-space: pre-wrap; }}
  </style>
</head>
<body>
  <h1>{html.escape(title or "未命名内容")}</h1>
  <div class="meta">来源：{html.escape(source_name or "-")} | 发布时间：{html.escape(publish_text)} | <a href="{html.escape(original_url or "#")}" target="_blank" rel="noopener noreferrer">原文链接</a></div>
  <article>{body_html}</article>
</body>
</html>"""


__all__ = [
    "_title_looks_like_url",
    "_looks_like_translation_refusal",
    "_reader_body_hash",
    "_extract_x_article_url",
    "_is_x_status_page_url",
    "_looks_like_x_interstitial_text",
    "_is_valid_translation_text",
    "_is_valid_title_translation",
    "_split_for_reader",
    "_build_reader_blocks",
    "_derive_title_from_body",
    "_clean_x_reader_body",
    "_build_clean_reader_html",
]
