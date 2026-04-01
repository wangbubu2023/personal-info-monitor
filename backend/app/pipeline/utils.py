"""Pipeline utility functions."""

import hashlib
import re
from datetime import datetime
from typing import List
from urllib.parse import unquote, urlparse

from app.utils.logger import get_logger
from app.utils.text import strip_html_tags

logger = get_logger(__name__)

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
    "collections",
    "latest",
    "library",
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
}

def normalize_external_id(external_id: str | None) -> str | None:
    """Normalize external_id to fit DB length constraints while staying stable."""
    if not external_id:
        return external_id
    if len(external_id) <= 255:
        return external_id
    digest = hashlib.sha1(external_id.encode("utf-8")).hexdigest()
    return f"hash:{digest}"

def normalize_extra_urls(extra_urls) -> List[str]:
    if not isinstance(extra_urls, list):
        return []
    seen = set()
    normalized: List[str] = []
    for raw in extra_urls:
        if not raw:
            continue
        candidate = str(raw).strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        normalized.append(candidate)
    return normalized

def get_source_urls(source) -> List[str]:
    """Get the full list of URLs to fetch for a given source."""
    metadata = source.metadata_ if isinstance(source.metadata_, dict) else {}
    extras = normalize_extra_urls(metadata.get("extra_urls"))
    urls = [source.url]
    for item in extras:
        if item != source.url:
            urls.append(item)
            
    # For website sources, avoid fetching multiple URLs that are mapped to the same RSS feed.
    source_type = source.type.value if hasattr(source.type, "value") else str(source.type).lower()
    if str(source_type) == "website":
        rss_map = metadata.get("rss_urls") if isinstance(metadata.get("rss_urls"), dict) else {}
        default_rss = rss_map.get(source.url) or metadata.get("rss_url")
        deduped_urls: List[str] = []
        seen_targets = set()
        for url in urls:
            target = rss_map.get(url) or default_rss or url
            target_key = str(target).strip()
            if not target_key or target_key in seen_targets:
                continue
            seen_targets.add(target_key)
            deduped_urls.append(url)
        if deduped_urls:
            urls = deduped_urls
    return urls

async def resolve_website_publish_time(raw_content: dict) -> datetime | None:
    """Resolve publish_time for website content with fallback to article page extraction."""
    publish_time = raw_content.get("publish_time")
    if isinstance(publish_time, str):
        try:
            return datetime.fromisoformat(publish_time.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            publish_time = None

    if isinstance(publish_time, datetime):
        return publish_time

    metadata = raw_content.get("metadata") or {}
    if metadata.get("publish_time_estimated"):
        url = raw_content.get("url")
        if url:
            try:
                from app.utils.publish_time import fetch_publish_time_from_url
                resolved = await fetch_publish_time_from_url(url)
                if resolved:
                    return resolved
            except Exception:
                return None
    return None

async def normalize_publish_time(raw_content: dict, source_type: str) -> datetime | None:
    """Normalize publish_time from raw content for freshness checks."""
    if source_type == "website":
        return await resolve_website_publish_time(raw_content)

    publish_time = raw_content.get("publish_time")
    if isinstance(publish_time, str):
        try:
            return datetime.fromisoformat(publish_time.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            return None
    if isinstance(publish_time, datetime):
        return publish_time
    return None

def dedupe_raw_contents(raw_contents: List[dict]) -> List[dict]:
    """Deduplicate merged contents from multiple URLs based on external_id, url or title."""
    seen = set()
    deduped = []
    for item in raw_contents:
        key = normalize_external_id(item.get("external_id")) or item.get("url") or item.get("title")
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


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
    """Return a rejection reason for obvious non-article website items."""
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
    text_is_thin = len(text) < 140 and _word_count(text) < 24 and len(html) < 2000
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
    if (
        section_like_url
        and text_is_thin
        and title_word_count <= 2
        and not any(ch.isdigit() for ch in title)
        and not re.search(r"[?!:;]", title)
    ):
        return "section_hub_without_article_body"

    return None
