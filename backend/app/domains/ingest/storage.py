"""Ingest stage for persisting raw Content objects.

Keyword notifications are handled later by :func:`app.domains.ingest.finish.finish_content`
after AI processing fills in keyword_matches.
"""

from typing import List, Tuple, Optional
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.models import Content
from app.pipeline.utils import normalize_external_id
from app.utils.logger import get_logger

logger = get_logger(__name__)


class StorageStage:

    @staticmethod
    def execute(db: Session, contents: List[Content]) -> Tuple[int, Optional[str]]:
        """Persist Content objects.

        Returns:
            Tuple of (saved_count, latest_saved_marker).
        """
        saved_count = 0
        latest_saved_marker = None

        for content in contents:
            try:
                with db.begin_nested():
                    db.add(content)
                    db.flush()
                    saved_count += 1

                    marker_candidate = normalize_external_id(content.external_id)
                    if marker_candidate and not latest_saved_marker:
                        latest_saved_marker = marker_candidate
            except IntegrityError:
                logger.info(f"Skipping duplicate content on insert: {content.external_id or content.original_url}")
                continue
            except Exception as e:
                logger.error(f"Error saving content {content.original_url}: {e}")
                continue

        return saved_count, latest_saved_marker
