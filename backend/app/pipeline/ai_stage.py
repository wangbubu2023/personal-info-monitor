"""Pipeline stage for processing content (AI summarization, translation).

.. deprecated::
    ``AIStage`` has **no production callers** as of 2026-05-19; it is
    referenced only by ``tests/test_pipeline_stages.py`` to lock in legacy
    behaviour. The PIM 模块化重构实施蓝图 v3 (§5.4, §7) schedules this
    module for removal in Phase 7 once the corresponding tests have been
    migrated or deleted.

    Do **not** add new imports of this module. New ingest/enrich flows
    must go through :mod:`app.tasks.process_tasks` (current) and later
    ``app.domains.ingest.finish_content`` /
    ``app.domains.enrich.content.reprocess`` (after Phase 3/4).
"""

import warnings
from typing import List

from app.models import Source, Keyword, Content
from app.processors import ContentProcessor
from app.utils.logger import get_logger

logger = get_logger(__name__)


class AIStage:
    """Legacy stage; will be removed in refactor Phase 7."""

    @staticmethod
    async def execute(source: Source, raw_contents: List[dict], keywords: List[Keyword]) -> List[Content]:
        """Execute the AI stage (translation, summarization, keyword extraction).

        .. deprecated::
            See module docstring. Slated for removal in Phase 7.
        """
        warnings.warn(
            "AIStage is deprecated and will be removed in refactor Phase 7; "
            "no production code currently calls it.",
            DeprecationWarning,
            stacklevel=2,
        )
        processor = ContentProcessor()
        processed_contents = []
        
        for raw_content in raw_contents:
            try:
                content = await processor.process(raw_content, source, keywords)
                processed_contents.append(content)
            except Exception as e:
                logger.error(f"Error AI-processing context for {raw_content.get('url', '')}: {e}")
                continue
                
        return processed_contents
