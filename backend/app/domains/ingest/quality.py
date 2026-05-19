"""Content-quality heuristics that decide whether a raw item is worth keeping.

The headline export is :func:`get_website_content_reject_reason`, which
returns a short machine-readable reason string when an item is obvious
non-article noise (navigation hubs, section titles, thin teaser snippets,
domain-specific section pages) and ``None`` when the item should be kept.

Phase 2 step 7 / Phase 3 step 1 of the refactor moved this logic out of
``app.pipeline.utils`` so:

* ``collectors`` can stop importing ``app.pipeline.*`` (蓝图 §2.3 边界规则)
* ``api`` can stop importing ``app.pipeline.*`` (same)
* the heuristics are co-located with the rest of the ingest domain
  (Phase 3 owns dedup / quality / scoring)

``app.pipeline.utils`` keeps a thin re-export shim so existing
``unittest.mock.patch`` targets remain valid; the shim is removed in
Phase 7.
"""

from __future__ import annotations

import re
from urllib.parse import unquote, urlparse

from app.utils.text import strip_html_tags


_STRONG_WEBSITE_NAV_TITLES = {
    "all topics",
    "case selections",
    "data and visuals",
    "hbr executive",
    "my library",
    "reading lists",
    "subscribe",
}

_DOMAIN_WEBSITE_SECTION_TITLES = {
    "hbr.org": {
        "gender",
        "innovation",
        "leadership",
        "latest",
        "managing teams",
        "managing yourself",
        "newsletters",
        "podcasts",
        "store",
        "strategy",
        "the magazine",
        "webinars",
        "work life balance",
    },
    "businessinsider.com": {
        "advertising",
        "careers",
        "law",
        "latest",
        "media",
        "personal finance",
        "real estate",
        "retail",
        "small business",
        "the better work project",
        "travel",
    },
    "techmeme.com": {
        "events",
        "about",
        "contact",
        "sponsor",
        "search",
    },
}

_DOMAIN_NON_ARTICLE_PATH_SEGMENTS = {
    "businessinsider.com": {
        "show",
        "shows",
        "guide",
        "guides",
        "video",
        "videos",
    },
}

_NON_ARTICLE_PATH_SEGMENTS = {
    "account",
    "author",
    "authors",
    "browse",
    "categories",
    "category",
    "channel",
    "channels",
    "collections",
    "index",
    "latest",
    "library",
    "list",
    "lists",
    "login",
    "menu",
    "newsletters",
    "section",
    "sections",
    "search",
    "signin",
    "subscribe",
    "subject",
    "subjects",
    "tag",
    "tags",
    "topic",
    "topics",
    # CJK Pinyin / Common patterns
    "zhuanti",
    "fenlei",
    "pindao",
    "huati",
}


def _normalize_host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower().strip()
    if host.startswith("www."):
        host = host[4:]
    return host


def _normalize_title_key(value: str) -> str:
    text = strip_html_tags(value or "")
    text = text.replace("&", " and ")
    text = text.replace("/", " ")
    text = text.replace("-", " ")
    text = re.sub(r"[^0-9a-z\u4e00-\u9fff ]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def _word_count(text: str) -> int:
    if not text:
        return 0
    return len(re.findall(r"[0-9A-Za-z\u4e00-\u9fff]+", text))


def _matches_known_title(title_key: str, known_titles: set[str]) -> bool:
    """Loose match for nav/section titles with optional branding suffix/prefix."""
    if not title_key:
        return False
    if title_key in known_titles:
        return True
    for phrase in known_titles:
        if title_key.startswith(phrase + " "):
            return True
        if title_key.endswith(" " + phrase):
            return True
    return False


def _same_site(source_url: str, candidate_url: str) -> bool:
    source_host = _normalize_host(source_url)
    candidate_host = _normalize_host(candidate_url)
    if not source_host or not candidate_host:
        return False
    return candidate_host == source_host or candidate_host.endswith("." + source_host)


def _host_matches_domain(host: str, domain: str) -> bool:
    if not host or not domain:
        return False
    return host == domain or host.endswith("." + domain)


def _looks_like_section_path(source_url: str, candidate_url: str) -> bool:
    if not candidate_url or not _same_site(source_url, candidate_url):
        return False

    parsed = urlparse(candidate_url)
    segments = [unquote(seg).strip().lower() for seg in parsed.path.split("/") if seg.strip()]
    if not segments:
        return True

    if any(seg in _NON_ARTICLE_PATH_SEGMENTS for seg in segments):
        return True

    tail = segments[-1]
    if "." in tail:
        return False
    tail_parts = [part for part in re.split(r"[-_]+", tail) if part]
    if tail_parts and tail_parts[-1] in {"hub", "index", "overview", "topics", "topic", "sections", "section"}:
        return True

    tail_word_count = len([part for part in re.split(r"[-_]+", tail) if part])
    has_digits = any(ch.isdigit() for ch in tail)

    if len(segments) == 1 and not has_digits and tail_word_count <= 4:
        return True

    if len(segments) <= 2 and not has_digits and "-" not in tail and tail.isalpha():
        return True

    return False


def get_website_content_reject_reason(source_url: str, raw_content: dict) -> str | None:
    """Return a rejection reason for obvious non-article website items.

    Returns one of:

    * ``"blocked_navigation_title"`` — title matches a hard-coded nav phrase
    * ``"blocked_domain_non_article_path"`` — domain-specific non-article URL
    * ``"blocked_section_hub_title"`` — section/topic hub disguised as content
    * ``"blocked_cjk_nav_pattern"`` — CJK / short nav title on a section URL
    * ``"low_content_single_phrase_link"`` — single-phrase, thin teaser snippet
    * ``None`` — keep the item (no rejection)
    """
    title = strip_html_tags(str(raw_content.get("title") or "")).strip()
    if not title:
        return None

    title_key = _normalize_title_key(title)
    if not title_key:
        return None

    if _matches_known_title(title_key, _STRONG_WEBSITE_NAV_TITLES):
        return "blocked_navigation_title"

    url = str(raw_content.get("url") or "").strip()
    text = strip_html_tags(str(raw_content.get("content") or "")).strip()
    html = str(raw_content.get("html") or "")

    # RUTHLESS SIGNAL CHECK:
    # 1. Very short text (< 250 chars) and few words (< 40) is likely noise.
    # 2. Content that is just a verbatim repeat of the title? Drop it.
    is_simple_repeat = title_key == _normalize_title_key(text) if text else False
    text_is_thin = (len(text) < 250 and _word_count(text) < 40 and len(html) < 2000) or is_simple_repeat
    parsed = urlparse(url) if url else None
    segments = [unquote(seg).strip().lower() for seg in (parsed.path.split("/") if parsed else []) if seg.strip()]
    section_like_url = _looks_like_section_path(source_url, url)
    source_host = _normalize_host(source_url)

    domain_titles = set()
    for domain, titles in _DOMAIN_WEBSITE_SECTION_TITLES.items():
        if _host_matches_domain(source_host, domain):
            domain_titles.update(titles)

    for domain, non_article_segments in _DOMAIN_NON_ARTICLE_PATH_SEGMENTS.items():
        if _host_matches_domain(source_host, domain):
            if text_is_thin and segments and any(seg in non_article_segments for seg in segments):
                return "blocked_domain_non_article_path"

    # Domain-level section hubs should be blocked even if page text is long.
    if section_like_url and _matches_known_title(title_key, domain_titles):
        return "blocked_section_hub_title"

    title_word_count = _word_count(title_key)
    # INCREASED STRICTNESS for CJK and short-title nav links.
    # We now block if title contains strong nav keywords even if it has digits/punctuation.
    if section_like_url and (title_word_count <= 3 or re.search(r"[【】|\|]", title)):
        return "blocked_cjk_nav_pattern"

    if (
        (section_like_url or title_word_count <= 2)
        and text_is_thin
        # If it's a section-like URL and thin text, we are MUCH more aggressive.
        and (not any(ch.isdigit() for ch in title) or section_like_url)
    ):
        return "low_content_single_phrase_link"

    return None


__all__ = ["get_website_content_reject_reason"]
