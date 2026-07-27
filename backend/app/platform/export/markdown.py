"""Export content to Markdown files with frontmatter."""

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import frontmatter
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.content import Content
from app.platform.export.html_markdown import render_html_markdown
from app.platform.observability.logger import get_logger

logger = get_logger(__name__)


class MarkdownExporter:
    """Export Content records to Markdown with YAML frontmatter."""

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir).expanduser().resolve()

    def export_content(self, content: Content) -> Path:
        """Export a single Content to a Markdown file."""
        path = self._resolve_path(content)
        
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.render_content_markdown(content), encoding="utf-8")
        return path

    def render_content_markdown(self, content: Content, *, include_full_content: bool = True) -> str:
        """Render one content item as Markdown without writing a file.

        ``include_full_content=False`` is used by on-demand downloads so exports
        include attribution and links without redistributing paid full text by
        default.
        """
        fm_data = self._build_frontmatter(content)
        body = self._build_body(content, include_full_content=include_full_content)
        return frontmatter.dumps(frontmatter.Post(body, **fm_data))

    def render_event_markdown(
        self,
        contents: list[Content],
        *,
        title: str | None = None,
        event_key: str | None = None,
    ) -> str:
        """Render a persisted Event with source timeline and attribution."""
        items = [content for content in contents if content]
        if not items:
            return "# Empty Event\n"

        primary = items[0]
        event_key = str(event_key or self._event_key(primary) or "").strip()
        fm_data = {
            "title": title or primary.translated_title or primary.title,
            "event_key": event_key,
            "content_count": len(items),
            "sources": [content.source.name for content in items if content.source],
            "pim_content_ids": [str(content.id) for content in items],
        }
        lines: list[str] = [
            f"# {title or primary.translated_title or primary.title or 'Untitled Event'}",
            "",
            "## 今日看点",
            "",
            primary.translated_summary or primary.summary or "暂无摘要。",
            "",
            "## 事件与来源",
            "",
            f"- 事件键：{event_key or '未归组'}",
            f"- 报道数：{len(items)}",
            f"- 独立来源数：{len({content.source_id for content in items if content.source_id})}",
            "",
            "## 时间线",
            "",
        ]
        for content in sorted(items, key=lambda c: (c.publish_time or c.fetched_at or datetime.min, str(c.id))):
            timestamp = content.publish_time or content.fetched_at
            source_name = content.source.name if content.source else "Unknown"
            lines.extend([
                f"- {timestamp.isoformat() if timestamp else '未知时间'} · {source_name} · {content.title}",
                f"  - PIM：pim://content/{content.id}",
                f"  - 原文：{content.original_url}",
            ])
            if content.summary:
                lines.append(f"  - 摘要：{content.summary.strip()}")
        lines.extend([
            "",
            "## 正文说明",
            "",
            "> Event 导出默认只包含标题、摘要、来源、时间线、PIM 链接、原文链接和归因，不复制完整付费/版权正文。",
            "",
        ])
        return frontmatter.dumps(frontmatter.Post("\n".join(lines).rstrip() + "\n", **fm_data))

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
        metadata = content.metadata_ if isinstance(content.metadata_, dict) else {}
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
            "pim_content_id": str(content.id),
            "pim_source_id": str(content.source_id) if content.source_id else None,
            "duplicate_group_id": metadata.get("duplicate_group_id"),
            "canonical_external_id": metadata.get("canonical_external_id"),
            "event_id": metadata.get("event_id"),
        }

    def _event_key(self, content: Content) -> str:
        metadata = content.metadata_ if isinstance(content.metadata_, dict) else {}
        return str(metadata.get("event_id") or "")

    def _build_body(self, content: Content, *, include_full_content: bool = True) -> str:
        metadata = content.metadata_ if isinstance(content.metadata_, dict) else {}
        lines: list[str] = []
        lines.extend([
            f"# {content.translated_title or content.title or 'Untitled'}",
            "",
            "## 来源与归因",
            "",
            f"- 来源：{content.source.name if content.source else 'Unknown'}",
            f"- 发布时间：{content.publish_time.isoformat() if content.publish_time else '未知'}",
            f"- PIM 内容 ID：{content.id}",
            f"- PIM 链接：pim://content/{content.id}",
            f"- 原文链接：{content.original_url}",
        ])
        if metadata.get("event_id"):
            lines.append(f"- 事件 ID：{metadata['event_id']}")
        if metadata.get("duplicate_group_id"):
            lines.append(f"- 近重复组：{metadata['duplicate_group_id']}")
        if metadata.get("canonical_external_id"):
            lines.append(f"- Canonical 外部 ID：{metadata['canonical_external_id']}")
        lines.append("")

        if content.summary:
            lines.extend(["## 摘要", "", content.summary.strip(), ""])
        if content.translated_summary:
            lines.extend(["## 摘要翻译", "", content.translated_summary.strip(), ""])

        full = content.full_content or ""
        if full and include_full_content:
            lines.extend(["## 正文", ""])
            if "<html" in full.lower() or "<p>" in full.lower() or "<article" in full.lower():
                try:
                    lines.append(render_html_markdown(full))
                except Exception:
                    lines.append(full.strip())
            else:
                lines.append(full.strip())
            lines.append("")
        elif full:
            lines.extend([
                "## 正文",
                "",
                "> 默认导出不包含完整正文，避免再分发可能受限的付费/版权内容。请通过上方 PIM 链接或原文链接阅读。",
                "",
            ])

        return "\n".join(lines).rstrip() + "\n"

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
