"""Pipeline stage for processing content (AI summarization, translation)."""

from typing import List
from app.models import Source, Keyword, Content
from app.processors import ContentProcessor
from app.utils.logger import get_logger

logger = get_logger(__name__)

class AIStage:
    
    @staticmethod
    async def execute(source: Source, raw_contents: List[dict], keywords: List[Keyword]) -> List[Content]:
        """
        Execute the AI stage (translation, summarization, keyword extraction).
        """
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
