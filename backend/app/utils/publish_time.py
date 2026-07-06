"""Publish time parsing and extraction helpers."""

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import aiohttp
from bs4 import BeautifulSoup

from app.utils.datetime import utcnow_naive
from app.utils.logger import get_logger

_CN_TZ = ZoneInfo("Asia/Shanghai")

logger = get_logger(__name__)


def _to_utc_naive(dt: datetime, assume_cn_tz: bool = False) -> datetime:
    """Convert datetime to UTC naive for DB consistency."""
    if dt.tzinfo is None:
        if assume_cn_tz:
            dt = dt.replace(tzinfo=_CN_TZ)
        else:
            dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def parse_publish_time_text(text: str) -> Optional[datetime]:
    """Parse common absolute/relative publish time strings to UTC naive."""
    if not text:
        return None

    cleaned = re.sub(r"\s+", " ", text).strip()
    now_utc = utcnow_naive()

    # ISO datetimes from JSON-LD/meta tags, e.g. 2026-07-02T01:02:03Z.
    if "T" in cleaned:
        try:
            return _to_utc_naive(datetime.fromisoformat(cleaned.replace("Z", "+00:00")))
        except ValueError:
            pass

    # Relative Chinese time, e.g. "2小时前", "30分钟前", "1天前"
    relative_patterns = [
        (r"(\d+)\s*分钟前", "minutes"),
        (r"(\d+)\s*小时前", "hours"),
        (r"(\d+)\s*天前", "days"),
    ]
    for pattern, unit in relative_patterns:
        m = re.search(pattern, cleaned)
        if m:
            value = int(m.group(1))
            if unit == "minutes":
                return now_utc - timedelta(minutes=value)
            if unit == "hours":
                return now_utc - timedelta(hours=value)
            return now_utc - timedelta(days=value)

    # Absolute Chinese datetime: 2026年02月10日 17:02
    m = re.search(
        r"(\d{4})年(\d{1,2})月(\d{1,2})日(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?",
        cleaned,
    )
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        hh = int(m.group(4) or 0)
        mm = int(m.group(5) or 0)
        ss = int(m.group(6) or 0)
        return _to_utc_naive(datetime(y, mo, d, hh, mm, ss), assume_cn_tz=True)

    # Absolute compact formats.
    fmts = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d",
    ]
    for fmt in fmts:
        try:
            dt = datetime.strptime(cleaned, fmt)
        except ValueError:
            # strptime only raises ValueError on format mismatch; keep trying.
            continue
        # For date-only values, assume local CN midnight for CN-oriented sites.
        return _to_utc_naive(dt, assume_cn_tz=True)

    # English month formats, e.g. "Feb 12, 2026 6:54 PM EST"
    tz_offsets = {
        "UTC": 0, "GMT": 0,
        "EST": -5, "EDT": -4,
        "CST": -6, "CDT": -5,
        "MST": -7, "MDT": -6,
        "PST": -8, "PDT": -7,
    }
    m = re.search(
        r"(?:[A-Za-z]{3},\s*)?([A-Za-z]{3,9}\s+\d{1,2},\s*\d{4}\s+\d{1,2}:\d{2}\s*(?:AM|PM))(?:\s+([A-Z]{2,4}))?",
        cleaned,
        flags=re.IGNORECASE,
    )
    if m:
        dt_part = m.group(1).strip()
        tz_abbr = (m.group(2) or "").upper().strip()
        for fmt in ("%b %d, %Y %I:%M %p", "%B %d, %Y %I:%M %p"):
            try:
                dt = datetime.strptime(dt_part, fmt)
            except ValueError:
                continue
            if tz_abbr in tz_offsets:
                dt = dt.replace(tzinfo=timezone(timedelta(hours=tz_offsets[tz_abbr])))
                return dt.astimezone(timezone.utc).replace(tzinfo=None)
            return _to_utc_naive(dt, assume_cn_tz=False)

    # Month-level dates used by some vendor blogs, e.g. "May 2026".
    m = re.fullmatch(r"([A-Za-z]{3,9})\s+(\d{4})", cleaned, flags=re.IGNORECASE)
    if m:
        for fmt in ("%b %Y", "%B %Y"):
            try:
                dt = datetime.strptime(cleaned, fmt)
            except ValueError:
                continue
            return _to_utc_naive(dt, assume_cn_tz=False)

    return None


def _extract_meta_publish_time(soup: BeautifulSoup) -> Optional[datetime]:
    """Prefer explicit metadata over body heuristics."""
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
        if not tag or not tag.get("content"):
            continue
        parsed = parse_publish_time_text(tag.get("content", ""))
        if parsed:
            return parsed
    return None


def _extract_jsonld_publish_time(soup: BeautifulSoup) -> Optional[datetime]:
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        text = (script.string or script.get_text() or "").strip()
        if not text:
            continue
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            # Many sites ship broken or comment-laden JSON-LD blocks; skip.
            continue

        candidates = obj if isinstance(obj, list) else [obj]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            for field in ("datePublished", "dateCreated", "uploadDate"):
                value = item.get(field)
                if not isinstance(value, str):
                    continue
                parsed = parse_publish_time_text(value)
                if parsed:
                    return parsed
    return None


def _extract_time_tag_publish_time(soup: BeautifulSoup) -> Optional[datetime]:
    for tag in soup.find_all("time"):
        dt_attr = (tag.get("datetime") or "").strip()
        if dt_attr:
            parsed = parse_publish_time_text(dt_attr)
            if parsed:
                return parsed
        text = tag.get_text(" ", strip=True)
        if not text:
            continue
        parsed = parse_publish_time_text(text)
        if parsed:
            return parsed
    return None


def _extract_labeled_publish_time(html: str) -> Optional[datetime]:
    label_patterns = [
        r"(发布时间|发表时间|发布于|更新时间|更新于)\s*[:：]?\s*([0-9]{4}[-/年][^<\n]{6,40})",
        r"(Published|Updated)\s*[:：]?\s*([A-Za-z]{3,9}\s+\d{1,2},\s*\d{4}[^<\n]{0,30})",
    ]
    snippet = html[:120000]
    for pattern in label_patterns:
        for match in re.finditer(pattern, snippet, flags=re.IGNORECASE):
            candidate = (match.group(2) or "").strip()
            parsed = parse_publish_time_text(candidate)
            if parsed:
                return parsed
    return None


def extract_publish_time_from_html(html: str) -> Optional[datetime]:
    """Extract publish time from page HTML meta/JSON-LD/body text."""
    if not html:
        return None

    soup = BeautifulSoup(html, "lxml")
    for extractor in (
        _extract_meta_publish_time,
        _extract_jsonld_publish_time,
        _extract_time_tag_publish_time,
    ):
        parsed = extractor(soup)
        if parsed:
            return parsed

    return _extract_labeled_publish_time(html)


async def fetch_publish_time_from_url(url: str, timeout: int = 12) -> Optional[datetime]:
    """Fetch article page and try extracting publish time.

    ``url`` originates from fetched page content (``raw_content["url"]``) and is
    therefore attacker-influenceable, so the request must go through the unified
    SSRF guard (which also re-validates every redirect target) rather than a raw
    aiohttp request.
    """
    # Local import keeps the security module off this util's import graph until
    # a website source actually needs publish-time backfill.
    from app.platform.security.ssrf import fetch_public_http_text

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        async with aiohttp.ClientSession() as session:
            result = await fetch_public_http_text(
                session,
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout),
            )
        if result.status != 200:
            return None
        return extract_publish_time_from_html(result.text)
    except ValueError as exc:
        # SSRF guard rejected the URL or a redirect target (private/internal
        # address). Treat as a normal "no publish time" outcome.
        logger.debug("fetch_publish_time_from_url(%s) blocked by SSRF guard: %s", url, exc)
        return None
    except (aiohttp.ClientError, TimeoutError, UnicodeDecodeError) as exc:
        # Network flakes and malformed responses are expected — log at debug
        # so the fetch loop can move on without polluting the warning stream.
        logger.debug("fetch_publish_time_from_url(%s) failed: %s", url, exc)
        return None
