"""Structured article-body extraction from publisher HTML.

Many news sites ship the canonical article body in JSON-LD, Next.js data,
or other page-owned JSON before client-side paywall widgets alter the DOM.
This helper extracts only same-page structured data; it does not change
headers, clear cookies, block scripts, or call archival services.
"""

from __future__ import annotations

import html as html_lib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.utils.datetime import user_timezone
from app.utils.publish_time import parse_publish_time_text
from app.utils.text import html_to_text_preserving_blocks, normalize_article_text, strip_html_tags
from app.utils.logger import get_logger


logger = get_logger(__name__)


ARTICLE_TYPES = {
    "article",
    "newsarticle",
    "blogposting",
    "reportagenewsarticle",
    "scholarlyarticle",
    "socialmediaposting",
}

BODY_KEYS = (
    "articleBody",
    "body",
    "bodyText",
    "BodyPlainText",
    "content",
    "contentHtml",
    "html",
    "text",
)

_DEFAULT_BODY_MIN_PAGE_RATIO = 0.30
_MIN_VISIBLE_TEXT_CHARS_FOR_RATIO_CHECK = 800
_MIN_FLAT_STRUCTURED_TEXT_CHARS = 1500
_VISIBLE_TEXT_EXCLUDED_TAGS = {
    "script",
    "style",
    "noscript",
    "template",
    "svg",
    "title",
    "meta",
    "link",
}
_PRISMIC_RICH_TEXT_TYPES = {
    "paragraph",
    "preformatted",
    "list-item",
    "o-list-item",
    "quote",
}
_PRISMIC_RELATED_SECTION_RE = re.compile(
    r"^(?:related|recommended|read next)\b.*(?:articles?|posts?|reading)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class StructuredArticleExtraction:
    text: str
    method: str
    title: str | None = None
    signals: dict[str, Any] = field(default_factory=dict)


def _loads_json(text: str) -> Any:
    text = (text or "").strip()
    if not text:
        raise ValueError("empty json")
    try:
        return json.loads(text)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("invalid or excessively nested json") from exc


def _loads_assigned_json_object(text: str, marker: str) -> Any:
    """Parse a JSON object assigned to a JS global, e.g. ``window.initialState=...``."""
    idx = (text or "").find(marker)
    if idx < 0:
        raise ValueError("marker not found")
    start = text.find("{", idx + len(marker))
    if start < 0:
        raise ValueError("object start not found")

    depth = 0
    in_string = False
    escaped = False
    for pos in range(start, len(text)):
        ch = text[pos]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return _loads_json(text[start : pos + 1])
    raise ValueError("object end not found")


def _iter_json_nodes(value: Any) -> Iterable[Any]:
    stack: list[tuple[Any, int]] = [(value, 0)]
    visited = 0
    while stack and visited < 10_000:
        node, depth = stack.pop()
        visited += 1
        yield node
        if depth >= 64:
            continue
        if isinstance(node, dict):
            stack.extend((child, depth + 1) for child in reversed(tuple(node.values())))
        elif isinstance(node, list):
            stack.extend((child, depth + 1) for child in reversed(node))


def _node_type_names(node: dict[str, Any]) -> set[str]:
    raw = node.get("@type") or node.get("type")
    values = raw if isinstance(raw, list) else [raw]
    return {str(item or "").strip().lower() for item in values if str(item or "").strip()}


def _clean_candidate_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        value = "\n\n".join(_clean_candidate_text(item) for item in value)
    elif isinstance(value, dict):
        for key in BODY_KEYS:
            if key in value:
                return _clean_candidate_text(value.get(key))
        value = " ".join(str(v) for v in value.values() if isinstance(v, str))
    else:
        value = str(value)

    text = html_lib.unescape(value).replace("\\n", "\n")
    if "<" in text and ">" in text:
        text = html_to_text_preserving_blocks(text)
    return normalize_article_text(text).strip()


def _paragraph_count(text: str) -> int:
    if not text:
        return 0
    parts = [p.strip() for p in re.split(r"\n{2,}|(?<=[.!?。！？])\s+", text) if p.strip()]
    meaningful = [p for p in parts if len(p) >= 40]
    if meaningful:
        return len(meaningful)
    return 1 if len(text) >= 80 else 0


def _passes_flatness_check(text: str, *, method: str, body_key: str) -> tuple[bool, dict[str, Any]]:
    signals = {
        "paragraph_count": _paragraph_count(text),
    }
    if len(text) <= _MIN_FLAT_STRUCTURED_TEXT_CHARS:
        return True, signals
    if "\n\n" in text or signals["paragraph_count"] > 2:
        return True, signals

    logger.debug(
        "Structured %s %s is suspiciously flat: body=%d paragraphs=%d; falling back",
        method,
        body_key,
        len(text),
        signals["paragraph_count"],
    )
    signals["rejected_reason"] = "suspicious_flat_text"
    return False, signals


def _title_from_node(node: dict[str, Any]) -> str | None:
    for key in ("headline", "name", "title"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return normalize_article_text(value).strip()
    return None


def _node_string(node: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            nested = _node_string(value, "@id", "url")
            if nested:
                return nested
    return None


def _safe_absolute_url(value: str | None, page_url: str | None = None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    absolute = urljoin(page_url or "", raw)
    parsed = urlparse(absolute)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None
    return absolute


def _canonical_url_from_soup(soup: BeautifulSoup, page_url: str | None = None) -> str | None:
    for link in soup.find_all("link"):
        rel_values = link.get("rel") or []
        if isinstance(rel_values, str):
            rel_values = [rel_values]
        if any(str(value).lower() == "canonical" for value in rel_values):
            canonical = _safe_absolute_url(link.get("href"), page_url)
            if canonical:
                return canonical

    for attr, key in (("property", "og:url"), ("name", "twitter:url")):
        tag = soup.find("meta", attrs={attr: key})
        canonical = _safe_absolute_url(tag.get("content") if tag else None, page_url)
        if canonical:
            return canonical

    return None


def _publish_time_from_node(node: dict[str, Any]) -> tuple[Any, str] | None:
    for key in ("datePublished", "dateCreated", "uploadDate", "dateModified"):
        value = node.get(key)
        if not isinstance(value, str):
            continue
        parsed = parse_publish_time_text(value)
        if parsed:
            return parsed, value
    return None


def _json_ld_metadata(soup: BeautifulSoup, page_url: str | None = None) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text() or ""
        try:
            data = _loads_json(raw.replace("\r", "").replace("\t", ""))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        for node in _iter_json_nodes(data):
            if not isinstance(node, dict):
                continue
            type_names = _node_type_names(node)
            has_publish_field = any(key in node for key in ("datePublished", "dateCreated", "uploadDate", "dateModified"))
            if type_names and not (type_names & ARTICLE_TYPES) and not has_publish_field:
                continue
            if not metadata.get("canonical_url"):
                canonical = _safe_absolute_url(_node_string(node, "url", "mainEntityOfPage", "@id"), page_url)
                if canonical:
                    metadata["canonical_url"] = canonical
            if not metadata.get("published_time"):
                published = _publish_time_from_node(node)
                if published:
                    metadata["published_time"], metadata["published_time_raw"] = published
            if metadata.get("canonical_url") and metadata.get("published_time"):
                return metadata
    return metadata


def _html_metadata_publish_time(soup: BeautifulSoup) -> tuple[Any, str] | None:
    meta_keys = [
        ("property", "article:published_time"),
        ("property", "og:published_time"),
        ("name", "publishdate"),
        ("name", "pubdate"),
        ("name", "date"),
        ("itemprop", "datePublished"),
    ]
    for attr, key in meta_keys:
        tag = soup.find("meta", attrs={attr: key})
        raw = str(tag.get("content") or "").strip() if tag else ""
        parsed = parse_publish_time_text(raw)
        if parsed:
            return parsed, raw

    for tag in soup.find_all("time"):
        raw = str(tag.get("datetime") or tag.get_text(" ", strip=True) or "").strip()
        parsed = parse_publish_time_text(raw)
        if parsed:
            return parsed, raw
    return None


def _best_body_from_node(node: dict[str, Any]) -> tuple[str, str] | None:
    candidates: list[tuple[str, str]] = []
    for key in BODY_KEYS:
        if key in node:
            text = _clean_candidate_text(node.get(key))
            if text:
                candidates.append((key, text))
    if not candidates:
        return None
    return max(candidates, key=lambda item: len(item[1]))


def _configured_body_min_page_ratio() -> float:
    raw = os.environ.get("PIM_STRUCTURED_BODY_MIN_RATIO")
    if raw is None:
        return _DEFAULT_BODY_MIN_PAGE_RATIO
    try:
        value = float(raw)
    except ValueError:
        logger.warning("Invalid PIM_STRUCTURED_BODY_MIN_RATIO=%r; using %.2f", raw, _DEFAULT_BODY_MIN_PAGE_RATIO)
        return _DEFAULT_BODY_MIN_PAGE_RATIO
    return max(0.0, min(value, 1.0))


def _visible_page_text(soup: BeautifulSoup) -> str:
    parts: list[str] = []
    for node in soup.find_all(string=True):
        parent = node.parent
        if parent and str(parent.name or "").lower() in _VISIBLE_TEXT_EXCLUDED_TAGS:
            continue
        text = str(node).strip()
        if text:
            parts.append(text)
    return normalize_article_text("\n".join(parts)).strip()


def _passes_page_ratio_check(
    text: str,
    *,
    visible_text_chars: int,
    min_ratio: float,
    method: str,
    body_key: str,
) -> tuple[bool, dict[str, Any]]:
    signals: dict[str, Any] = {
        "visible_text_chars": visible_text_chars,
        "body_min_page_ratio": min_ratio,
    }
    if min_ratio <= 0 or visible_text_chars < _MIN_VISIBLE_TEXT_CHARS_FOR_RATIO_CHECK:
        return True, signals

    ratio = len(text) / max(1, visible_text_chars)
    signals["body_page_ratio"] = round(ratio, 4)
    if ratio >= min_ratio:
        return True, signals

    logger.debug(
        "Structured %s %s too small for visible page text: body=%d visible=%d ratio=%.1f%% < %.1f%%; falling back",
        method,
        body_key,
        len(text),
        visible_text_chars,
        ratio * 100,
        min_ratio * 100,
    )
    signals["rejected_reason"] = "body_page_ratio_too_low"
    return False, signals


def _extract_from_json_ld(
    soup: BeautifulSoup,
    min_chars: int,
    *,
    visible_text_chars: int,
    min_ratio: float,
    rejections: list[dict[str, Any]] | None = None,
) -> StructuredArticleExtraction | None:
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text() or ""
        try:
            data = _loads_json(raw.replace("\r", "").replace("\t", ""))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue

        best: StructuredArticleExtraction | None = None
        for node in _iter_json_nodes(data):
            if not isinstance(node, dict):
                continue
            type_names = _node_type_names(node)
            if type_names and not (type_names & ARTICLE_TYPES):
                continue
            body = _best_body_from_node(node)
            if not body:
                continue
            body_key, text = body
            if len(text) < min_chars:
                if rejections is not None and len(rejections) < 12:
                    rejections.append(
                        {
                            "method": "json_ld",
                            "body_key": body_key,
                            "chars": len(text),
                            "rejected_reason": "too_short",
                        }
                    )
                continue
            flat_ok, flat_signals = _passes_flatness_check(
                text,
                method="json_ld",
                body_key=body_key,
            )
            if not flat_ok:
                if rejections is not None and len(rejections) < 12:
                    rejections.append(
                        {
                            "method": "json_ld",
                            "body_key": body_key,
                            "chars": len(text),
                            **flat_signals,
                        }
                    )
                continue
            accepted, ratio_signals = _passes_page_ratio_check(
                text,
                visible_text_chars=visible_text_chars,
                min_ratio=min_ratio,
                method="json_ld",
                body_key=body_key,
            )
            if not accepted:
                if rejections is not None and len(rejections) < 12:
                    rejections.append(
                        {
                            "method": "json_ld",
                            "body_key": body_key,
                            "chars": len(text),
                            **flat_signals,
                            **ratio_signals,
                        }
                    )
                continue
            candidate = StructuredArticleExtraction(
                text=text,
                method="json_ld",
                title=_title_from_node(node),
                signals={"body_key": body_key, "chars": len(text), **flat_signals, **ratio_signals},
            )
            if best is None or len(candidate.text) > len(best.text):
                best = candidate
        if best:
            return best
    return None


def _extract_from_next_data(
    soup: BeautifulSoup,
    min_chars: int,
    *,
    visible_text_chars: int,
    min_ratio: float,
) -> StructuredArticleExtraction | None:
    script = soup.select_one("script#__NEXT_DATA__")
    if not script:
        return None
    try:
        data = _loads_json(script.string or script.get_text() or "")
    except (TypeError, ValueError, json.JSONDecodeError):
        return None

    best: tuple[str, str] | None = None
    title: str | None = None
    for node in _iter_json_nodes(data):
        if isinstance(node, dict):
            if not title:
                title = _title_from_node(node)
            body = _best_body_from_node(node)
            if body and len(body[1]) >= min_chars and (best is None or len(body[1]) > len(best[1])):
                best = body
    if not best:
        return None
    body_key, text = best
    flat_ok, flat_signals = _passes_flatness_check(
        text,
        method="next_data",
        body_key=body_key,
    )
    if not flat_ok:
        return None
    accepted, ratio_signals = _passes_page_ratio_check(
        text,
        visible_text_chars=visible_text_chars,
        min_ratio=min_ratio,
        method="next_data",
        body_key=body_key,
    )
    if not accepted:
        return None
    return StructuredArticleExtraction(
        text=text,
        method="next_data",
        title=title,
        signals={"body_key": body_key, "chars": len(text), **flat_signals, **ratio_signals},
    )


def _prismic_rich_text_blocks(value: Any) -> list[str]:
    """Return visible text blocks from a Prismic rich-text array.

    Images intentionally contribute no alt text: alt is presentation metadata,
    not a sentence in the article body.
    """
    if not isinstance(value, list):
        return []

    blocks: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").strip().lower()
        if item_type == "image":
            continue
        if item_type not in _PRISMIC_RICH_TEXT_TYPES and not re.fullmatch(r"heading[1-6]", item_type):
            continue
        text = normalize_article_text(str(item.get("text") or "")).strip()
        if text:
            blocks.append(text)
    return blocks


def _prismic_section_title(primary: dict[str, Any]) -> str:
    blocks = _prismic_rich_text_blocks(primary.get("title"))
    return blocks[0] if blocks else ""


def _extract_from_prismic_next_data(
    soup: BeautifulSoup,
    min_chars: int,
    *,
    visible_text_chars: int,
    min_ratio: float,
) -> StructuredArticleExtraction | None:
    """Extract the current Prismic article embedded in a Next.js page.

    Prismic publishers commonly SSR only an intro while placing the remaining
    sections in ``props.pageProps.page.body``. The same payload may also carry
    large ``read_next_posts`` records, so this extractor follows only the
    explicitly item-scoped ``page`` path.
    """
    script = soup.select_one("script#__NEXT_DATA__")
    if not script:
        return None
    try:
        data = _loads_json(script.string or script.get_text() or "")
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None

    page = data.get("props", {}).get("pageProps", {}).get("page")
    if not isinstance(page, dict):
        return None

    body_slices = page.get("body")
    if not isinstance(body_slices, list):
        return None

    parts: list[str] = []
    for key in ("excerpt_title", "excerpt", "intro_section_title", "intro_section_body"):
        parts.extend(_prismic_rich_text_blocks(page.get(key)))

    section_count = 0
    skipped_related_sections = 0
    for item in body_slices:
        if not isinstance(item, dict) or str(item.get("slice_type") or "") != "content_section":
            continue
        primary = item.get("primary")
        if not isinstance(primary, dict):
            continue
        title = _prismic_section_title(primary)
        if title and _PRISMIC_RELATED_SECTION_RE.match(title):
            skipped_related_sections += 1
            continue
        content_blocks = _prismic_rich_text_blocks(primary.get("content_block"))
        if not content_blocks:
            continue
        if title:
            parts.append(title)
        parts.extend(content_blocks)
        section_count += 1

    source_blocks = _prismic_rich_text_blocks(page.get("sources"))
    if source_blocks:
        parts.append("Sources")
        parts.extend(source_blocks)

    text = normalize_article_text("\n\n".join(parts)).strip()
    if section_count < 1 or len(text) < min_chars:
        return None

    flat_ok, flat_signals = _passes_flatness_check(
        text,
        method="prismic_next_data",
        body_key="props.pageProps.page",
    )
    if not flat_ok:
        return None
    accepted, ratio_signals = _passes_page_ratio_check(
        text,
        visible_text_chars=visible_text_chars,
        min_ratio=min_ratio,
        method="prismic_next_data",
        body_key="props.pageProps.page",
    )
    if not accepted:
        return None

    title_blocks = _prismic_rich_text_blocks(page.get("title"))
    return StructuredArticleExtraction(
        text=text,
        method="prismic_next_data",
        title=title_blocks[0] if title_blocks else None,
        signals={
            "body_key": "props.pageProps.page",
            "chars": len(text),
            "section_count": section_count,
            "source_count": len(source_blocks),
            "skipped_related_sections": skipped_related_sections,
            **flat_signals,
            **ratio_signals,
        },
    )


def _cls_article_detail(data: Any) -> dict[str, Any] | None:
    """Return CLS' item-scoped Next.js article payload when present."""

    if not isinstance(data, dict):
        return None
    detail = (
        data.get("props", {})
        .get("pageProps", {})
        .get("articleDetail")
    )
    if not isinstance(detail, dict):
        return None
    content = _clean_candidate_text(detail.get("content"))
    article_id = detail.get("id")
    if not content or article_id in (None, ""):
        return None
    return detail


def _cls_published_time(detail: dict[str, Any]) -> tuple[datetime, str] | None:
    raw = detail.get("ctime")
    try:
        epoch = int(raw)
    except (TypeError, ValueError):
        return None
    if epoch <= 0:
        return None
    try:
        return datetime.fromtimestamp(epoch, tz=timezone.utc), str(raw)
    except (OverflowError, OSError, ValueError):
        return None


def _extract_from_cls_next_data(
    soup: BeautifulSoup,
    min_chars: int,
    *,
    visible_text_chars: int,
    min_ratio: float,
) -> StructuredArticleExtraction | None:
    """Extract the current 财联社 item from its item-scoped Next.js payload.

    CLS telegraphs are commonly shorter than the generic 120-character body
    floor. Their ``articleDetail`` object is already scoped to the requested
    item, so applying the page-length ratio would incorrectly discard the
    canonical body and fall back to navigation/footer text.
    """

    del min_chars, visible_text_chars, min_ratio
    script = soup.select_one("script#__NEXT_DATA__")
    if not script:
        return None
    try:
        data = _loads_json(script.string or script.get_text() or "")
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    detail = _cls_article_detail(data)
    if not detail:
        return None

    content = _clean_candidate_text(detail.get("content"))
    title = _clean_candidate_text(detail.get("title")) or None
    published = _cls_published_time(detail)
    text = content
    signals: dict[str, Any] = {
        "body_key": "props.pageProps.articleDetail.content",
        "chars": len(content),
        "article_id": str(detail.get("id")),
    }
    if published:
        published_at, raw = published
        local_time = published_at.astimezone(user_timezone())
        text = f"{local_time.strftime('%Y年%m月%d日 %H:%M:%S')}\n\n{content}"
        signals["published_time"] = published_at.isoformat()
        signals["published_time_raw"] = raw
    return StructuredArticleExtraction(
        text=normalize_article_text(text),
        method="cls_next_data",
        title=title,
        signals=signals,
    )


def _extract_from_36kr_newsflash_state(
    soup: BeautifulSoup,
    min_chars: int,
    *,
    visible_text_chars: int,
    min_ratio: float,
) -> StructuredArticleExtraction | None:
    """Extract the canonical body from 36Kr newsflash detail bootstrap state.

    36Kr newsflash pages render the current item, the next item, latest list,
    hot list, and footer in the same DOM. Generic readability extraction can
    therefore blend unrelated entries into the article body. The server-side
    ``window.initialState.newsflashDetail.detailData.data`` object carries the
    current newsflash body directly, so prefer it when present.
    """
    del visible_text_chars, min_ratio  # This state path is already item-scoped.

    for script in soup.find_all("script"):
        raw = script.string or script.get_text() or ""
        if "window.initialState" not in raw or "newsflashDetail" not in raw:
            continue
        try:
            data = _loads_assigned_json_object(raw, "window.initialState")
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        detail = (
            data.get("newsflashDetail", {})
            .get("detailData", {})
            .get("data", {})
        )
        if not isinstance(detail, dict):
            continue
        text = _clean_candidate_text(detail.get("widgetContent"))
        if len(text) < min_chars:
            continue
        title = _clean_candidate_text(detail.get("widgetTitle")) or None
        return StructuredArticleExtraction(
            text=text,
            method="36kr_newsflash_state",
            title=title,
            signals={"body_key": "newsflashDetail.detailData.data.widgetContent", "chars": len(text)},
        )
    return None


def _extract_from_wallstreetcn_article_body(
    soup: BeautifulSoup,
    min_chars: int,
    *,
    visible_text_chars: int,
    min_ratio: float,
) -> StructuredArticleExtraction | None:
    """Extract the server-rendered body of a public 华尔街见闻 article.

    The current site is Svelte-rendered and ships the article itself in
    ``section._articleBody_*``.  Generic readability sees the fixed header,
    author row, related links, and app-install prompt as one document; member
    URLs, meanwhile, return an HTTP error shell with no such section.  Keeping
    this selector scoped to the canonical public body makes both cases
    explicit: public articles get only their paragraphs and inaccessible ones
    do not masquerade as articles.
    """
    del visible_text_chars, min_ratio
    section = soup.select_one("article > section[class*='articleBody']")
    if section is None:
        return None
    text = normalize_article_text(html_to_text_preserving_blocks(str(section)))
    if len(text) < min_chars:
        return None
    title_node = soup.select_one("article > header h1") or soup.select_one("h1")
    title = _clean_candidate_text(title_node.get_text(" ", strip=True)) if title_node else None
    signals: dict[str, Any] = {
        "body_key": "article > section._articleBody_*",
        "chars": len(text),
        "site": "wallstreetcn",
    }
    time_node = soup.select_one("article > header time[datetime]") or soup.select_one("time[datetime]")
    raw_time = str(time_node.get("datetime") or "").strip() if time_node else ""
    if raw_time:
        try:
            published = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
            signals["published_time"] = published.astimezone(timezone.utc).isoformat()
            signals["published_time_raw"] = raw_time
        except ValueError:
            pass
    return StructuredArticleExtraction(
        text=text,
        method="wallstreetcn_article_body",
        title=title or None,
        signals=signals,
    )


def extract_structured_article(
    html: str,
    *,
    min_chars: int = 120,
    rejections: list[dict[str, Any]] | None = None,
) -> StructuredArticleExtraction | None:
    """Return the best same-page structured article body, if available."""
    if not html:
        return None
    soup = BeautifulSoup(html, "lxml")
    visible_text_chars = len(_visible_page_text(soup))
    min_ratio = _configured_body_min_page_ratio()
    for extractor in (
        _extract_from_cls_next_data,
        _extract_from_36kr_newsflash_state,
        _extract_from_wallstreetcn_article_body,
        _extract_from_json_ld,
        _extract_from_prismic_next_data,
        _extract_from_next_data,
    ):
        kwargs: dict[str, Any] = {
            "visible_text_chars": visible_text_chars,
            "min_ratio": min_ratio,
        }
        if extractor is _extract_from_json_ld:
            kwargs["rejections"] = rejections
        result = extractor(soup, min_chars, **kwargs)
        if result:
            return result
    return None


def extract_article_page_metadata(html: str, *, page_url: str | None = None) -> dict[str, Any]:
    """Extract canonical URL and publish time from already-fetched article HTML."""
    if not html:
        return {}
    soup = BeautifulSoup(html, "lxml")
    metadata = _json_ld_metadata(soup, page_url)
    wallstreetcn = _extract_from_wallstreetcn_article_body(
        soup,
        1,
        visible_text_chars=0,
        min_ratio=0,
    )
    if wallstreetcn:
        published = wallstreetcn.signals.get("published_time")
        if published:
            metadata["published_time"] = datetime.fromisoformat(str(published))
            metadata["published_time_raw"] = wallstreetcn.signals.get("published_time_raw")
    script = soup.select_one("script#__NEXT_DATA__")
    if script:
        try:
            data = _loads_json(script.string or script.get_text() or "")
        except (TypeError, ValueError, json.JSONDecodeError):
            data = None
        detail = _cls_article_detail(data)
        published = _cls_published_time(detail) if detail else None
        if published:
            metadata["published_time"], metadata["published_time_raw"] = published
    canonical = _canonical_url_from_soup(soup, page_url) or metadata.get("canonical_url")
    if canonical:
        metadata["canonical_url"] = canonical
    if not metadata.get("published_time"):
        published = _html_metadata_publish_time(soup)
        if published:
            metadata["published_time"], metadata["published_time_raw"] = published
    return metadata


__all__ = ["StructuredArticleExtraction", "extract_article_page_metadata", "extract_structured_article"]
