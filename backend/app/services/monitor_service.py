"""Monitoring service for managing source fetching."""

from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.domains.sources.scheduling import get_due_sources, next_fetch_at_for
from app.models import Source
from app.utils.logger import get_logger

logger = get_logger(__name__)


class MonitorService:
    """Service for managing content monitoring."""

    def __init__(self, db: Session):
        self.db = db

    def get_due_sources(self) -> List[Source]:
        """Get sources that are due for fetching. Failed sources use exponential backoff.

        Delegates to :func:`app.domains.sources.scheduling.get_due_sources` so
        the read-side and the scheduler share the same jittered interval and
        next-fetch instant.
        """
        return get_due_sources(self.db)

    def get_source_status(self, source_id: UUID) -> Dict:
        """Get detailed status of a source."""
        source = self.db.query(Source).filter(Source.id == source_id).first()

        if not source:
            return {"error": "Source not found"}

        next_fetch = next_fetch_at_for(source)

        from app.models import Content
        content_count = self.db.query(Content).filter(Content.source_id == source_id).count()
        
        return {
            "id": str(source.id),
            "name": source.name,
            "type": source.type.value if hasattr(source.type, 'value') else str(source.type),
            "url": source.url,
            "enabled": source.enabled,
            "fetch_interval": source.fetch_interval,
            "last_fetched_at": source.last_fetched_at.isoformat() if source.last_fetched_at else None,
            "next_fetch_at": next_fetch.isoformat() if next_fetch else None,
            "error_count": source.error_count,
            "last_error": source.last_error,
            "content_count": content_count
        }
    
    def get_all_sources_status(self) -> List[Dict]:
        """Get status of all sources."""
        sources = self.db.query(Source).all()
        return [self.get_source_status(source.id) for source in sources]
    
    def pause_source(self, source_id: UUID) -> bool:
        """Pause a source (disable fetching)."""
        source = self.db.query(Source).filter(Source.id == source_id).first()
        
        if not source:
            return False
        
        source.enabled = False
        self.db.commit()
        
        logger.info(f"Paused source: {source.name}")
        return True
    
    def resume_source(self, source_id: UUID) -> bool:
        """Resume a paused source."""
        source = self.db.query(Source).filter(Source.id == source_id).first()
        
        if not source:
            return False
        
        source.enabled = True
        source.error_count = 0  # Reset error count
        self.db.commit()
        
        logger.info(f"Resumed source: {source.name}")
        return True
    
    def reset_source_errors(self, source_id: UUID) -> bool:
        """Reset error count for a source."""
        source = self.db.query(Source).filter(Source.id == source_id).first()
        
        if not source:
            return False
        
        source.error_count = 0
        source.last_error = None
        self.db.commit()
        
        return True
    
    def get_health_stats(self) -> Dict:
        """Get overall monitoring health statistics."""
        sources = self.db.query(Source).all()
        
        total = len(sources)
        enabled = sum(1 for s in sources if s.enabled)
        with_errors = sum(1 for s in sources if s.error_count > 0)
        healthy = sum(1 for s in sources if s.enabled and s.error_count == 0)
        
        return {
            "total_sources": total,
            "enabled_sources": enabled,
            "disabled_sources": total - enabled,
            "sources_with_errors": with_errors,
            "healthy_sources": healthy,
            "health_percentage": round(healthy / total * 100, 1) if total > 0 else 0
        }
