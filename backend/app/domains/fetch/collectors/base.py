"""Base collector class for all data collectors."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from app.utils.datetime import utcnow_naive
from app.models import Source
from app.utils.cookies import normalize_cookie_dict
from app.utils.logger import get_logger
from app.utils.ssrf import assert_public_http_target

logger = get_logger(__name__)


class BaseCollector(ABC):
    """Abstract base class for all content collectors."""
    
    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)

    def get_runtime_auth(self, source: Source) -> Dict[str, Any]:
        """Runtime auth payload injected by fetch task."""
        auth = getattr(source, "_runtime_auth", None)
        return auth if isinstance(auth, dict) else {}

    def get_runtime_cookies(self, source: Source) -> Dict[str, str]:
        """Runtime cookies parsed from auth credentials."""
        auth = self.get_runtime_auth(source)
        credentials = auth.get("credentials", {}) if isinstance(auth, dict) else {}
        return normalize_cookie_dict(credentials.get("cookies"))

    def get_runtime_browser_session(self, source: Source) -> Dict[str, Any]:
        """Persistent browser session payload injected by fetch task."""
        auth = self.get_runtime_auth(source)
        browser_session = auth.get("browser_session") if isinstance(auth, dict) else None
        return browser_session if isinstance(browser_session, dict) else {}
    
    async def _check_ssrf(self, url: str) -> None:
        """Check URL against SSRF before fetching."""
        await assert_public_http_target(url)

    @abstractmethod
    async def fetch(self, source: Source) -> List[Dict[str, Any]]:
        """
        Fetch content from the source.
        
        Args:
            source: The Source model instance containing configuration.
        
        Returns:
            List of content dictionaries with keys:
            - external_id: Optional unique identifier from the source
            - title: Content title
            - content: Full content or description
            - url: Original URL
            - publish_time: Publication datetime
            - metadata: Additional platform-specific data
        """
        pass
    
    async def should_fetch(self, source: Source) -> bool:
        """Check if the source should be fetched based on interval."""
        from datetime import datetime, timedelta
        
        if not source.last_fetched_at:
            return True
        
        next_fetch_time = source.last_fetched_at + timedelta(minutes=source.fetch_interval)
        return utcnow_naive() >= next_fetch_time
    
    def filter_new_content(
        self,
        contents: List[Dict[str, Any]],
        last_content_id: Optional[str]
    ) -> List[Dict[str, Any]]:
        """Filter out content that was already fetched."""
        if not last_content_id:
            return contents

        marker_index = -1
        for i, content in enumerate(contents):
            if content.get("external_id") == last_content_id:
                marker_index = i
                break
        if marker_index < 0:
            return contents

        def _as_datetime(value):
            from datetime import datetime

            if isinstance(value, datetime):
                return value
            if isinstance(value, str):
                try:
                    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
                except Exception as exc:
                    logger.debug("Failed to parse datetime %r: %s", value, exc)
                    return None
            return None

        first_ts = _as_datetime(contents[0].get("publish_time")) if contents else None
        last_ts = _as_datetime(contents[-1].get("publish_time")) if contents else None
        if first_ts and last_ts:
            is_desc = first_ts >= last_ts
            return contents[:marker_index] if is_desc else contents[marker_index + 1:]

        # Unknown ordering: prefer avoiding false negatives.
        if marker_index == 0:
            return contents[1:]
        return contents[:marker_index]
    
    def validate_content(self, content: Dict[str, Any]) -> bool:
        """Validate that content has required fields."""
        required_fields = ["title", "url"]
        return all(content.get(field) for field in required_fields)
