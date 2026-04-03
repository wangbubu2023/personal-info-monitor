"""ProbeResult data class shared by all probe strategies."""

from typing import Any, Dict, Optional

from app.utils.datetime import to_iso_z, utcnow_naive


class ProbeResult:
    """Result of a source probe."""

    def __init__(
        self,
        status: str = "unknown",       # ok, warning, error, unknown
        strategy: str = "none",         # rss, scrape, js, rsshub, api, none
        rss_url: Optional[str] = None,
        message: str = "",
        sample_count: int = 0,
    ):
        self.status = status
        self.strategy = strategy
        self.rss_url = rss_url
        self.message = message
        self.sample_count = sample_count

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "strategy": self.strategy,
            "rss_url": self.rss_url,
            "message": self.message,
            "sample_count": self.sample_count,
            "probed_at": to_iso_z(utcnow_naive()),
        }
