"""Pipeline stage for normalizing and gating contents (freshness, duplicates)."""

from typing import List, Tuple
from sqlalchemy.orm import Session

from app.models import Source, Content
from app.utils.datetime import utcnow_naive
from app.utils.logger import get_logger
from app.pipeline.dedupe import handle_external_id_duplicate
from app.pipeline.utils import (
    get_website_content_reject_reason,
    normalize_external_id,
    normalize_publish_time,
)

logger = get_logger(__name__)

class NormalizerStage:
    
    @staticmethod
    async def execute(db: Session, source: Source, raw_contents: List[dict], manual_trigger: bool) -> Tuple[List[dict], int]:
        """
        Execute the normalizer stage.
        Filters out contents that are duplicate in DB or too stale.
        Returns:
            Tuple containing:
            - List of valid raw content dicts to process further
            - Integer count of skipped stale items
        """
        valid_contents = []
        stale_skipped = 0
        
        for raw_content in raw_contents:
            source_type = source.type.value if hasattr(source.type, "value") else source.type

            if str(source_type).lower() == "website":
                reject_reason = get_website_content_reject_reason(source.url, raw_content)
                if reject_reason:
                    logger.info(
                        "Skipping low-signal website content (%s): %s [%s]",
                        reject_reason,
                        str(raw_content.get("title") or "").strip(),
                        str(raw_content.get("url") or "").strip(),
                    )
                    continue

            # Check for duplicates before processing
            external_id = normalize_external_id(raw_content.get("external_id"))
            if external_id:
                raw_content["external_id"] = external_id
                if handle_external_id_duplicate(db, source, raw_content, external_id):
                    continue
            
            # Freshness gate: fetched_at - publish_time must be <= threshold.
            metadata = source.metadata_ or {}
            configured_max_lag = metadata.get("max_fetch_lag_minutes")
            
            if manual_trigger:
                effective_max_lag_minutes = int(configured_max_lag) if configured_max_lag is not None else 10080
            elif configured_max_lag is not None:
                effective_max_lag_minutes = int(configured_max_lag)
            else:
                effective_max_lag_minutes = 60
                
            publish_time = await normalize_publish_time(raw_content, str(source_type))
            if publish_time:
                raw_content["publish_time"] = publish_time
                lag_minutes = (utcnow_naive() - publish_time).total_seconds() / 60
                if lag_minutes > effective_max_lag_minutes:
                    stale_skipped += 1
                    logger.info(
                        f"Skipping stale content ({int(lag_minutes)}m>{effective_max_lag_minutes}m): "
                        f"{raw_content.get('url', '')}"
                    )
                    continue

            # Semantic dedupe for website feeds
            raw_title = str(raw_content.get("title") or "").strip()
            if str(source_type).lower() == "website" and raw_title and publish_time:
                semantic_existing = db.query(Content).filter(
                    Content.source_id == source.id,
                    Content.title == raw_title,
                    Content.publish_time == publish_time,
                ).first()
                if semantic_existing:
                    logger.info(f"Skipping semantic-duplicate website content: {raw_title}")
                    continue

            valid_contents.append(raw_content)

        return valid_contents, stale_skipped
