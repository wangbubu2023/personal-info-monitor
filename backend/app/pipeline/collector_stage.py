"""Pipeline stage for collecting raw contents from sources."""

from typing import List, Optional, Tuple, Any

from sqlalchemy.orm import Session

from app.models import Source, AuthConfig
import app.utils.url as url_utils
from app.utils.logger import get_logger
from app.collectors import get_collector

from app.domains.fetch.auth import (
    auth_warning_entry,
    cookie_hydration_warning_entry,
    maybe_refresh_auth_cookies,
    try_parse_auth_credentials,
)
from app.platform.browser import build_browser_session_runtime
from app.domains.sources.status import merge_warning_messages
from app.pipeline.utils import get_source_urls, dedupe_raw_contents

logger = get_logger(__name__)


async def fetch_at_ephemeral_source_url(collector, source: Source, fetch_url: str):
    """Run ``collector.fetch`` while temporarily overriding ``source.url`` (restored in ``finally``)."""
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
            Tuple containing:
            - List of raw content dicts
            - A combined warning message (if any)
            - The primary warning tuple (type, severity, localized_message) (if any)
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
                        db.commit()
                        db.refresh(source)
                        logger.info(f"Auto-bound auth config {cfg.id} to source {source.id}")
                        break

        # Resolve browser_session first so we can short-circuit password
        # auto-login when a logged-in on-disk profile is already available.
        # Otherwise password auth on captcha-hard sites (WSJ et al.) runs a
        # doomed auto-login that the site blocks with a challenge, poisoning
        # the fetch with a false-positive ``auth_captcha`` warning even though
        # the actual Playwright fetch later reads valid cookies from the
        # persistent profile.
        browser_session = None
        if str(source_type).lower() in ("website", "x"):
            browser_session = build_browser_session_runtime(db, source)

        runtime_auth = {}
        auth_warning = None
        if source.auth_config:
            creds = try_parse_auth_credentials(source.auth_config)
            session_auth_ready = bool(browser_session and browser_session.get("auth_ready"))
            if session_auth_ready:
                logger.info(
                    "Skipping password auto-login for source %s: recently validated browser session %s "
                    "already provides usable on-disk cookies",
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
            # X 源沿用 runtime_auth.credentials.cookies 从 auth_config 里取 cookie
            # （浏览器会话会自动把 profile 里的 cookies 同步过去）。这里把
            # ``browser_session`` 也塞进 runtime_auth 只是为了后续 X collector
            # 想直连 profile 时不用再改 pipeline。
            runtime_auth["browser_session"] = browser_session

        if runtime_auth:
            setattr(source, "_runtime_auth", runtime_auth)
        else:
            runtime_auth = None

        warning_entries: List[Tuple[str, str, str]] = []
        auth_entry = auth_warning_entry(auth_warning)
        if auth_entry:
            warning_entries.append(auth_entry)
        
        # Get collector for source type
        collector = get_collector(source_type)
        
        # Fetch content across primary + extra URLs.
        source_urls = get_source_urls(source)
        raw_contents = []
        for fetch_url in source_urls:
            try:
                fetched = await fetch_at_ephemeral_source_url(collector, source, fetch_url)
                if fetched:
                    raw_contents.extend(fetched)
            except Exception as e:
                logger.error(f"Error fetching from URL {fetch_url}: {e}")
                continue

        raw_contents = dedupe_raw_contents(raw_contents)
        cookie_entry = cookie_hydration_warning_entry(source, runtime_auth)
        if cookie_entry:
            warning_entries.append(cookie_entry)
            
        merged_warning = merge_warning_messages(*[item[2] for item in warning_entries])
        primary_warning = next((w for w in warning_entries if w[1] == "error"), warning_entries[0] if warning_entries else None)
        
        if raw_contents and source.last_content_id and str(source_type).lower() != "website" and len(source_urls) == 1:
            raw_contents = collector.filter_new_content(raw_contents, source.last_content_id)

        return raw_contents, merged_warning, primary_warning
