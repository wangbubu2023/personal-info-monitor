"""Cookie parsing helpers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http.cookies import SimpleCookie
from typing import Any

from app.utils.url import host_matches


def _extract_cookie_expiry(item: dict[str, Any]) -> float | None:
    for key in ("expires", "expirationDate", "expiry"):
        raw = item.get(key)
        if raw in (None, "", 0, "0", -1, "-1"):
            continue
        if isinstance(raw, (int, float)):
            return float(raw)
        try:
            return float(str(raw).strip())
        except (TypeError, ValueError):
            pass
        try:
            return parsedate_to_datetime(str(raw)).timestamp()
        except (TypeError, ValueError, IndexError, OverflowError):
            continue
    return None


def _cookie_item_matches_host(item: dict[str, Any], site_host: str | None) -> bool:
    if not site_host:
        return True
    domain = str(item.get("domain") or item.get("host") or "").strip().lstrip(".").lower()
    if not domain:
        return True
    return host_matches(site_host, domain)


def _normalize_cookie_items(
    items: list[Any],
    *,
    site_host: str | None = None,
    now: datetime | None = None,
) -> dict[str, str]:
    now_ts = (now or datetime.now(timezone.utc)).timestamp()
    cleaned: dict[str, str] = {}

    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("key") or "").strip()
        value = item.get("value")
        if not name or value is None:
            continue
        if not _cookie_item_matches_host(item, site_host):
            continue
        expires_at = _extract_cookie_expiry(item)
        if expires_at is not None and expires_at <= now_ts:
            continue
        cleaned[name] = str(value)

    return cleaned


def normalize_cookie_dict(
    raw: Any,
    *,
    site_host: str | None = None,
    now: datetime | None = None,
) -> dict[str, str]:
    """Normalize cookies payload to a plain dict."""
    if isinstance(raw, dict):
        if any(key in raw for key in ("name", "value", "domain", "expires", "expirationDate")):
            return _normalize_cookie_items([raw], site_host=site_host, now=now)
        cleaned: dict[str, str] = {}
        for k, v in raw.items():
            key = str(k or "").strip()
            if not key or v is None:
                continue
            cleaned[key] = str(v)
        return cleaned

    if isinstance(raw, (list, tuple)):
        return _normalize_cookie_items(list(raw), site_host=site_host, now=now)

    if isinstance(raw, str):
        stripped = raw.strip()
        if stripped.startswith("[") or stripped.startswith("{"):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                parsed = None
            if parsed is not None:
                return normalize_cookie_dict(parsed, site_host=site_host, now=now)
        return parse_cookie_string(raw)

    return {}


def parse_cookie_string(cookie_text: str) -> dict[str, str]:
    """
    Parse cookies from browser-copied cookie string.

    Supports:
    - `a=1; b=2`
    - multiline variants
    """
    text = (cookie_text or "").strip()
    if not text:
        return {}

    parser = SimpleCookie()
    normalized = "; ".join([seg.strip() for seg in text.replace("\n", ";").split(";") if seg.strip()])
    try:
        parser.load(normalized)
    except Exception:
        return {}

    return {k: v.value for k, v in parser.items() if k and v.value is not None}


def cookie_domains_for_host(host: str) -> list[str]:
    """Expand cookie domains for host + common subdomain coverage."""
    raw = (host or "").strip().lower().lstrip(".")
    if not raw:
        return []

    result: list[str] = []

    def _add(domain: str) -> None:
        if domain and domain not in result:
            result.append(domain)

    _add(raw)
    _add(f".{raw}")

    parts = raw.split(".")
    if len(parts) >= 2:
        apex = ".".join(parts[-2:])
        _add(apex)
        _add(f".{apex}")

    return result
