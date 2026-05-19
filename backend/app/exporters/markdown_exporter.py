"""Export content to Markdown files with frontmatter."""

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import frontmatter
from markdownify import markdownify as md
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.content import Content
from app.utils.logger import get_logger

logger = get_logger(__name__)


class MarkdownExporter:
    """Export Content records to Markdown with YAML frontmatter."""

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir).expanduser().resolve()

    def export_content(self, content: Content) -> Path:
        """Export a single Content to a Markdown file."""
        fm_data = self._build_frontmatter(content)
        body = self._build_body(content)
        path = self._resolve_path(content)
        
        path.parent.mkdir(parents=True, exist_ok=True)
        
        post = frontmatter.Post(body, **fm_data)
        path.write_text(frontmatter.dumps(post), encoding="utf-8")
        return path

    async def export_incremental(self, db: AsyncSession, since: datetime) -> int:
        """Export all content updated since the given datetime."""
        from sqlalchemy.orm import selectinload
        stmt = select(Content).options(selectinload(Content.source)).where(Content.updated_at >= since)
        result = await db.execute(stmt)
        contents = result.scalars().all()
        
        count = 0
        for c in contents:
            try:
                self.export_content(c)
                count += 1
            except Exception as e:
                logger.error("Failed to export content %s: %s", c.id, e)
        return count

    def _build_frontmatter(self, content: Content) -> Dict[str, Any]:
        source_name = content.source.name if content.source else "Unknown"
        return {
            "title": content.title,
            "translated_title": content.translated_title,
            "source": source_name,
            "type": content.content_type,
            "url": content.original_url,
            "date": content.publish_time.isoformat() if content.publish_time else None,
            "fetched": content.fetched_at.isoformat() if content.fetched_at else None,
            "read": bool(content.read_status),
            "favorited": bool(content.favorited),
            "archived": bool(content.archived),
        }

    def _build_body(self, content: Content) -> str:
        body = ""
        if content.summary:
            body += f"## Summary\n\n{content.summary}\n\n"
        if content.translated_summary:
            body += f"## 摘要翻译\n\n{content.translated_summary}\n\n"
            
        full = content.full_content or ""
        if full:
            body += f"## Full Content\n\n"
            if "<html" in full.lower() or "<p>" in full.lower() or "<article" in full.lower():
                try:
                    body += md(full)
                except Exception:
                    body += full
            else:
                body += full
                
        return body

    def _resolve_path(self, content: Content) -> Path:
        source_name = content.source.name if content.source else "Unknown"
        # Sanitize source name for directory
        safe_source = "".join(c for c in source_name if c.isalnum() or c in " -_").strip()
        if not safe_source:
            safe_source = "default"
            
        pub_time = content.publish_time or content.fetched_at
        if not pub_time:
            from app.utils.datetime import utcnow_naive
            pub_time = utcnow_naive()
            
        date_str = pub_time.strftime("%Y-%m-%d")
        
        safe_title = "".join(c for c in (content.title or "untitled") if c.isalnum() or c in " -_").strip()
        safe_title = safe_title[:50]  # truncate long titles
        if not safe_title:
            safe_title = str(content.id)[:8]
            
        filename = f"{date_str}-{safe_title}.md"
        return self.output_dir / "sources" / safe_source / filename
