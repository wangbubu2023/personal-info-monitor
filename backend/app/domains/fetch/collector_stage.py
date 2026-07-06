"""Fetch-domain collector stage.

This stage resolves source auth/runtime context, calls the source-type
collector across primary + extra URLs, and returns raw content plus structured
warnings to the coordinator.
"""

from __future__ import annotations

import re
from typing import Any, List, Optional, Tuple

from sqlalchemy.orm import Session

import app.utils.url as url_utils
from app.domains.fetch.auth import (
    auth_warning_entry,
    cookie_hydration_warning_entry,
    maybe_refresh_auth_cookies,
    try_parse_auth_credentials,
)
from app.domains.fetch.collectors import get_collector
from app.domains.fetch.session_alerts import session_health_warning_entry
from app.domains.sources.status import merge_warning_messages
from app.models import AuthConfig, Source
from app.platform.browser import build_browser_session_runtime
from app.utils.logger import get_logger
from app.utils.url import canonical_article_external_id, normalize_external_id

logger = get_logger(__name__)


def _allow_password_login(source: Source) -> bool:
    metadata = source.metadata_ if isinstance(source.metadata_, dict) else {}
    return metadata.get("allow_password_login") is True


def normalize_extra_urls(extra_urls: Any) -> List[str]:
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


def get_source_urls(source: Source) -> List[str]:
    """Get the full list of URLs to fetch for a given source."""
    metadata = source.metadata_ if isinstance(source.metadata_, dict) else {}
    extras = normalize_extra_urls(metadata.get("extra_urls"))
    urls = [source.url]
    for item in extras:
        if item != source.url:
            urls.append(item)

    # For website sources, avoid fetching multiple URLs that map to the same RSS feed.
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


def dedupe_raw_contents(raw_contents: List[dict]) -> List[dict]:
    """Deduplicate merged contents from multiple URLs by external_id, URL, or title."""
    seen = set()
    deduped = []
    for item in raw_contents:
        eid = normalize_external_id(item.get("external_id"))
        url = (item.get("url") or "").strip()
        url_key = canonical_article_external_id(url) if url else ""
        key = eid or url_key or item.get("title")
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _classify_fetch_failure(exc: Exception | None, last_error: str) -> Tuple[str, str, str]:
    """Turn an all-URLs-failed fetch error into a structured warning tuple."""
    from app.domains.fetch.failures import classify_exception, to_warning_entry

    if exc is not None:
        return to_warning_entry(classify_exception(exc))
    detail = last_error.strip() or "all fetch attempts failed"
    return ("fetch_failed", "error", f"抓取失败：所有请求均未成功（{detail}）"[:500])


def _is_youtube_channel_marker(source_type: Any, last_content_id: str | None) -> bool:
    if str(source_type).lower() != "youtube" or not last_content_id:
        return False
    return bool(re.fullmatch(r"UC[a-zA-Z0-9_-]{22}", str(last_content_id)))


async def fetch_at_ephemeral_source_url(collector, source: Source, fetch_url: str):
    """Run ``collector.fetch`` while temporarily overriding ``source.url``."""
    prev = source.url
    source.url = fetch_url
    try:
        return await collector.fetch(source)
    finally:
        source.url = prev


class CollectorStage:
    @staticmethod
    async def execute(db: Session, source: Source) -> Tuple[List[dict], Optional[str], Optional[Tuple[str, str, str]]]:
        """
        Execute the collection stage.

        Returns:
            Tuple of raw content dicts, combined warning message, and primary
            warning tuple ``(type, severity, localized_message)``.
        """
        # Auto-bind website auth config by domain when source.auth_config_id is empty.
        source_type = source.type.value if hasattr(source.type, "value") else source.type
        if str(source_type).lower() == "website" and not source.auth_config_id:
            source_host = url_utils.normalize_host(source.url)
            if source_host:
                candidates = db.query(AuthConfig).all()
                for cfg in candidates:
                    cfg_host = url_utils.normalize_host(cfg.site_url)
                    if not cfg_host:
                        continue
                    if url_utils.host_matches(source_host, cfg_host):
                        source.auth_config_id = cfg.id
                        source.auth_required = True
                        logger.info(f"Auto-bound auth config {cfg.id} to source {source.id}")
                        break

        # Resolve browser_session first so password auto-login can be skipped
        # when a recently validated on-disk profile already has cookies.
        browser_session = None
        if str(source_type).lower() in ("website", "x"):
            browser_session = build_browser_session_runtime(db, source)

        runtime_auth = {}
        auth_warning = None
        if source.auth_config:
            creds = try_parse_auth_credentials(source.auth_config)
            session_auth_ready = bool(browser_session and browser_session.get("auth_ready"))
            session_present = bool(browser_session)
            password_login_allowed = _allow_password_login(source)
            if session_auth_ready:
                logger.info(
                    "Skipping password auto-login for source %s: recently validated browser session %s "
                    "already provides usable on-disk cookies",
                    source.id,
                    browser_session.get("id"),
                )
            elif session_present and not password_login_allowed:
                auth_warning = (
                    "浏览器会话优先：已跳过密码自动登录；"
                    "如需回退密码登录，请设置 allow_password_login=true"
                )
                logger.info(
                    "Skipping password auto-login for source %s: browser session %s is bound "
                    "and allow_password_login is not enabled",
                    source.id,
                    browser_session.get("id"),
                )
            else:
                creds, auth_warning = await maybe_refresh_auth_cookies(db, source, creds)
            auth_type = source.auth_config.auth_type.value if hasattr(source.auth_config.auth_type, "value") else str(source.auth_config.auth_type).lower()
            runtime_auth.update({
                "auth_type": auth_type,
                "credentials": creds,
                "login_url": source.auth_config.login_url,
                "login_selectors": source.auth_config.login_selectors or {},
            })

        if browser_session:
            runtime_auth["browser_session"] = browser_session

        if runtime_auth:
            setattr(source, "_runtime_auth", runtime_auth)
        else:
            runtime_auth = None

        warning_entries: List[Tuple[str, str, str]] = []
        auth_entry = auth_warning_entry(auth_warning)
        if auth_entry:
            warning_entries.append(auth_entry)

        collector = get_collector(source_type)

        source_urls = get_source_urls(source)
        raw_contents = []
        fetch_success_count = 0
        fetch_error_count = 0
        last_fetch_error = ""
        last_fetch_exc: Exception | None = None
        for fetch_url in source_urls:
            try:
                fetched = await fetch_at_ephemeral_source_url(collector, source, fetch_url)
                fetch_success_count += 1
                if fetched:
                    raw_contents.extend(fetched)
            except Exception as e:  # noqa: BLE001 - one URL can fail while another succeeds
                fetch_error_count += 1
                last_fetch_error = str(e)
                last_fetch_exc = e
                logger.error(f"Error fetching from URL {fetch_url}: {e}")
                continue

        if source_urls and fetch_success_count == 0 and fetch_error_count > 0:
            warning_entries.append(_classify_fetch_failure(last_fetch_exc, last_fetch_error))

        raw_contents = dedupe_raw_contents(raw_contents)
        cookie_entry = cookie_hydration_warning_entry(source, runtime_auth)
        if cookie_entry:
            warning_entries.append(cookie_entry)
        session_entry = session_health_warning_entry(source)
        if session_entry:
            warning_entries.append(session_entry)

        merged_warning = merge_warning_messages(*[item[2] for item in warning_entries])
        primary_warning = next((w for w in warning_entries if w[1] == "error"), warning_entries[0] if warning_entries else None)

        if (
            raw_contents
            and source.last_content_id
            and str(source_type).lower() != "website"
            and not _is_youtube_channel_marker(source_type, source.last_content_id)
            and len(source_urls) == 1
        ):
            raw_contents = collector.filter_new_content(raw_contents, source.last_content_id)

        return raw_contents, merged_warning, primary_warning


__all__ = [
    "CollectorStage",
    "dedupe_raw_contents",
    "fetch_at_ephemeral_source_url",
    "get_source_urls",
    "logger",
    "normalize_external_id",
    "normalize_extra_urls",
]
