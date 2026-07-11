"""CRUD routes for content management."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.interfaces.http.content_shared import _serialize_content
from app.database import get_async_db
from app.domains.ingest.visibility import visible_content_clause
from app.domains.score.feedback import content_feedback_snapshot, record_score_feedback_event
from app.models import Content, Source
from app.schemas.content import ContentListResponse, ContentResponse, ContentUpdate, FavoriteBody
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()
MAX_CONTENTS_PAGE_SIZE = 200


def _safe_export_filename(title: str | None) -> str:
    safe = "".join(
        c for c in (title or "untitled")
        if c.isascii() and (c.isalnum() or c in " -_")
    ).strip()
    safe = "-".join(safe.split())[:80]
    return safe or "content"


def _content_ilike_search_clause(search: str):
    """Substring match on indexed text columns (covers CJK where FTS5 MATCH is unreliable)."""
    safe = (search or "").strip()[:120].replace("%", "").replace("_", "")
    if not safe:
        return None
    pat = f"%{safe}%"
    return or_(
        Content.title.ilike(pat),
        Content.summary.ilike(pat),
        Content.translated_title.ilike(pat),
        Content.translated_summary.ilike(pat),
        Content.full_content.ilike(pat),
        Content.source.has(or_(Source.name.ilike(pat), Source.url.ilike(pat))),
    )


async def _sqlite_has_content_fts(db: AsyncSession) -> bool:
    """True when FTS5 virtual table exists (fresh DBs / tests may omit migrations)."""
    r = await db.execute(text("SELECT 1 FROM sqlite_master WHERE name = 'content_fts' LIMIT 1"))
    return r.first() is not None


@router.get("", response_model=ContentListResponse)
async def list_contents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=MAX_CONTENTS_PAGE_SIZE),
    source_id: Optional[UUID] = None,
    source_type: Optional[str] = None,
    read_status: Optional[bool] = None,
    favorited: Optional[bool] = None,
    archived: Optional[bool] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_async_db),
):
    """List all content with pagination and filters."""
    query = select(Content).options(selectinload(Content.source))
    count_query = select(func.count(Content.id))
    query = query.filter(visible_content_clause(include_archived=archived is True))
    count_query = count_query.filter(visible_content_clause(include_archived=archived is True))

    if source_id:
        query = query.filter(Content.source_id == source_id)
        count_query = count_query.filter(Content.source_id == source_id)
    if source_type:
        query = query.filter(Content.content_type == source_type)
        count_query = count_query.filter(Content.content_type == source_type)
    if read_status is not None:
        query = query.filter(Content.read_status == read_status)
        count_query = count_query.filter(Content.read_status == read_status)
    if favorited is not None:
        query = query.filter(Content.favorited == favorited)
        count_query = count_query.filter(Content.favorited == favorited)
    if archived is True:
        archived_clause = Content.archived.is_(True)
    else:
        archived_clause = or_(Content.archived.is_(False), Content.archived.is_(None))
    query = query.filter(archived_clause)
    count_query = count_query.filter(archived_clause)
    if date_from:
        query = query.filter(Content.publish_time >= date_from)
        count_query = count_query.filter(Content.publish_time >= date_from)
    if date_to:
        query = query.filter(Content.publish_time <= date_to)
        count_query = count_query.filter(Content.publish_time <= date_to)
    if search:
        from app.utils.fts_query import build_sqlite_fts5_match_expression

        like_clause = _content_ilike_search_clause(search)
        match_expr = build_sqlite_fts5_match_expression(search)
        fts_ok = await _sqlite_has_content_fts(db)

        # FTS5 对中文分词/短语与索引一致性依赖较强，常与「标题里明明有却搜不到」并存；
        # 与 ILIKE 子串 OR：任一路命中即可（英文仍可由 FTS 提相关度，此处未排序加权）。
        if fts_ok and match_expr is not None:
            fts_subquery = (
                select(text("id"))
                .select_from(text("content_fts"))
                .where(text("content_fts MATCH :search_term"))
            )
            if like_clause is not None:
                combined = or_(Content.id.in_(fts_subquery), like_clause)
                query = query.filter(combined).params(search_term=match_expr)
                count_query = count_query.filter(combined).params(search_term=match_expr)
            else:
                query = query.filter(Content.id.in_(fts_subquery)).params(search_term=match_expr)
                count_query = count_query.filter(Content.id.in_(fts_subquery)).params(search_term=match_expr)
        elif like_clause is not None:
            query = query.filter(like_clause)
            count_query = count_query.filter(like_clause)

    total = await db.scalar(count_query) or 0
    offset = (page - 1) * page_size
    query = query.order_by(Content.publish_time.desc().nulls_last(), Content.fetched_at.desc()).offset(offset).limit(page_size)

    result = await db.execute(query)
    contents = result.scalars().all()
    items = [ContentResponse(**_serialize_content(c)) for c in contents]
    total_pages = (total + page_size - 1) // page_size

    return ContentListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/{content_id}", response_model=ContentResponse)
async def get_content(
    content_id: UUID,
    db: AsyncSession = Depends(get_async_db),
):
    """Get a specific content by ID."""
    result = await db.execute(
        select(Content)
        .options(selectinload(Content.source))
        .filter(Content.id == content_id)
    )
    content = result.scalar_one_or_none()
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")
    return ContentResponse(**_serialize_content(content))


@router.patch("/{content_id}", response_model=ContentResponse)
async def update_content(
    content_id: UUID,
    content_data: ContentUpdate,
    db: AsyncSession = Depends(get_async_db),
):
    """Update content (mark as read, favorite, archive)."""
    result = await db.execute(
        select(Content)
        .options(selectinload(Content.source))
        .filter(Content.id == content_id)
    )
    content = result.scalar_one_or_none()
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")

    payload = content_data.model_dump(exclude_unset=True)
    explicit_user_edited = "is_user_edited" in payload
    interaction_events: list[tuple[str, bool]] = []
    text_fields = ("title", "summary", "full_content")
    content_text_changed = False

    for field, value in payload.items():
        if field == "is_user_edited":
            continue
        old = getattr(content, field)
        setattr(content, field, value)
        if field in text_fields and value != old:
            content_text_changed = True
        if field == "read_status":
            interaction_events.append(("open", bool(value)))
        elif field == "favorited":
            interaction_events.append(("star", bool(value)))
        elif field == "archived":
            interaction_events.append(("hide", bool(value)))

    if explicit_user_edited:
        content.is_user_edited = bool(payload["is_user_edited"])
    elif content_text_changed:
        content.is_user_edited = True

    for event_type, event_value in interaction_events:
        await record_score_feedback_event(
            db,
            content,
            event_type=event_type,
            event_value=event_value,
            snapshot=content_feedback_snapshot(content, {"source": "contents.patch"}),
        )

    await db.commit()
    await db.refresh(content)

    return ContentResponse(**_serialize_content(content))


@router.get("/events/export-md", response_class=Response)
async def export_event_markdown(
    event_key: str = Query(..., min_length=1, max_length=255),
    db: AsyncSession = Depends(get_async_db),
):
    """Download an event-like duplicate group as attribution-first Markdown."""
    from app.platform.export import MarkdownExporter

    key = event_key.strip()
    result = await db.execute(
        select(Content)
        .options(selectinload(Content.source))
        .filter(
            or_(
                func.json_extract(Content.metadata_, "$.event_id") == key,
                func.json_extract(Content.metadata_, "$.duplicate_group_id") == key,
                func.json_extract(Content.metadata_, "$.canonical_external_id") == key,
            )
        )
        .order_by(Content.publish_time.asc().nulls_last(), Content.fetched_at.asc())
        .limit(200)
    )
    contents = list(result.scalars().all())
    if not contents:
        raise HTTPException(status_code=404, detail="Event not found")

    exporter = MarkdownExporter("/tmp/pim-event-export-preview")
    markdown = exporter.render_event_markdown(contents)
    filename = f"{_safe_export_filename(key)}.md"
    return Response(
        content=markdown,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{content_id}/export-md", response_class=Response)
async def export_content_markdown(
    content_id: UUID,
    db: AsyncSession = Depends(get_async_db),
):
    """Download a single content item as attribution-first Markdown."""
    from app.platform.export import MarkdownExporter

    result = await db.execute(
        select(Content)
        .options(selectinload(Content.source))
        .filter(Content.id == content_id)
    )
    content = result.scalar_one_or_none()
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")

    exporter = MarkdownExporter("/tmp/pim-single-export-preview")
    markdown = exporter.render_content_markdown(content, include_full_content=False)
    filename = f"{_safe_export_filename(content.title)}.md"
    return Response(
        content=markdown,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/export-md")
async def manual_export_markdown(db: AsyncSession = Depends(get_async_db)):
    """Manually trigger incremental markdown export."""
    from datetime import timedelta
    from app.utils.datetime import utcnow_naive
    from app.platform.config.system_settings import get_system_settings_async
    from app.platform.export import MarkdownExporter

    settings = await get_system_settings_async(db)
    if not settings.get("markdown_export_enabled"):
        raise HTTPException(status_code=400, detail="Markdown export is disabled in settings.")

    export_dir = settings.get("markdown_export_dir") or "~/.pim/knowledge-base"
    exporter = MarkdownExporter(export_dir)
    since = utcnow_naive() - timedelta(hours=24)
    
    try:
        count = await exporter.export_incremental(db, since)
        return {"status": "success", "exported_count": count, "dir": export_dir}
    except Exception:
        logger.exception("Markdown export failed")
        raise HTTPException(
            status_code=500,
            detail="Markdown export failed; see server logs for details.",
        ) from None


@router.post("/{content_id}/read")
async def mark_as_read(
    content_id: UUID,
    db: AsyncSession = Depends(get_async_db),
):
    """Mark content as read."""
    content = await db.scalar(select(Content).filter(Content.id == content_id))
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")

    content.read_status = True
    await record_score_feedback_event(
        db,
        content,
        event_type="open",
        event_value=True,
        snapshot=content_feedback_snapshot(content, {"source": "contents.read"}),
    )
    await db.commit()
    return {"message": "Content marked as read"}


@router.patch("/{content_id}/favorite")
async def set_favorite(
    content_id: UUID,
    body: FavoriteBody,
    db: AsyncSession = Depends(get_async_db),
):
    """Set favorite status (idempotent)."""
    content = await db.scalar(select(Content).filter(Content.id == content_id))
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")

    content.favorited = body.favorited
    await record_score_feedback_event(
        db,
        content,
        event_type="star",
        event_value=body.favorited,
        snapshot=content_feedback_snapshot(content, {"source": "contents.favorite"}),
    )
    await db.commit()
    return {"message": "Favorite updated", "favorited": content.favorited}


@router.delete("/{content_id}")
async def delete_content(
    content_id: UUID,
    db: AsyncSession = Depends(get_async_db),
):
    """Delete a content item."""
    content = await db.scalar(select(Content).filter(Content.id == content_id))
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")

    await db.delete(content)
    await db.commit()
    return {"message": "Content deleted successfully"}
