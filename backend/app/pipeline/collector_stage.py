"""Pipeline stage for collecting raw contents from sources."""

import copy
from typing import List, Optional, Tuple, Any

from sqlalchemy.orm import Session

from app.models import Source, AuthConfig
import app.utils.url as url_utils
from app.utils.logger import get_logger
import asyncio
from app.collectors import get_collector

from app.tasks.fetch_auth_helpers import (
    auth_warning_entry,
    build_browser_session_runtime,
    cookie_hydration_warning_entry,
    maybe_refresh_auth_cookies,
    try_parse_auth_credentials,
)
from app.tasks.fetch_orchestrator import merge_warning_messages
from app.pipeline.utils import get_source_urls, dedupe_raw_contents

logger = get_logger(__name__)

class CollectorStage:
    
    @staticmethod
    def execute(db: Session, source: Source) -> Tuple[List[dict], Optional[str], Optional[Tuple[str, str, str]]]:
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

        # Pass decrypted auth credentials to collector runtime context.
        runtime_auth = {}
        auth_warning = None
        if source.auth_config:
            creds = try_parse_auth_credentials(source.auth_config)
            creds, auth_warning = maybe_refresh_auth_cookies(db, source, creds)
            auth_type = source.auth_config.auth_type.value if hasattr(source.auth_config.auth_type, "value") else str(source.auth_config.auth_type).lower()
            runtime_auth.update({
                "auth_type": auth_type,
                "credentials": creds,
                "login_url": source.auth_config.login_url,
                "login_selectors": source.auth_config.login_selectors or {},
            })

        if str(source_type).lower() == "website":
            browser_session = build_browser_session_runtime(db, source)
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
        
        # Get collector for source type
        collector = get_collector(source_type)
        
        # Fetch content across primary + extra URLs.
        source_urls = get_source_urls(source)
        raw_contents = []
        original_url = source.url
        
        # Fixing V6-P2-3: try/finally to ensure source.url restores
        try:
            for fetch_url in source_urls:
                try:
                    source.url = fetch_url
                    fetched = asyncio.run(collector.fetch(source))
                    if fetched:
                        raw_contents.extend(fetched)
                except Exception as e:
                    logger.error(f"Error fetching from URL {fetch_url}: {e}")
                    continue
        finally:
            source.url = original_url
            
        raw_contents = dedupe_raw_contents(raw_contents)
        cookie_entry = cookie_hydration_warning_entry(source, runtime_auth)
        if cookie_entry:
            warning_entries.append(cookie_entry)
            
        merged_warning = merge_warning_messages(*[item[2] for item in warning_entries])
        primary_warning = next((w for w in warning_entries if w[1] == "error"), warning_entries[0] if warning_entries else None)
        
        # If all content already fetched, we can filter them here if the collector supports it
        # However, website pages are often not strictly ordered
        if raw_contents and source.last_content_id and str(source_type).lower() != "website" and len(source_urls) == 1:
            raw_contents = collector.filter_new_content(raw_contents, source.last_content_id)

        return raw_contents, merged_warning, primary_warning
