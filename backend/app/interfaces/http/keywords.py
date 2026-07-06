"""API routes for keyword management."""

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.database import get_async_db
from app.models import Keyword
from app.domains.ingest.keywords.rules import (
    compute_stored_equivalent_terms,
    dedupe_keywords_case_insensitive,
    keyword_identity_key,
    normalize_keyword_value,
    normalize_manual_equivalent_terms,
)
from app.schemas.keyword import (
    KeywordBatchCreate,
    KeywordBatchCreateResponse,
    KeywordBatchUpdate,
    KeywordBatchUpdateResponse,
    KeywordCreate,
    KeywordUpdate,
    KeywordResponse,
    KeywordListResponse,
)
router = APIRouter()


def _enum_value(value: object) -> str:
    return str(getattr(value, "value", value))


def _include_auto_bool(keyword: Keyword) -> bool:
    """DB 旧行可能为 NULL；默认与模型一致为 True。"""
    raw = getattr(keyword, "include_auto_equivalent_terms", None)
    if raw is None:
        return True
    return bool(raw)


async def _background_refresh_keyword_matches() -> None:
    """Recompute stored keyword matches on all content (after keyword config changes)."""
    from app.tasks.process_tasks import update_keyword_matches

    await update_keyword_matches()


def _enqueue_keyword_match_refresh(background_tasks: BackgroundTasks) -> None:
    """Run after response so DB commit is visible to the refresh job."""
    background_tasks.add_task(_background_refresh_keyword_matches)


def _normalize_batch_keywords(raw_keywords: list[str]) -> tuple[list[str], list[str]]:
    normalized_inputs: list[str] = []
    for raw_keyword in raw_keywords:
        keyword = normalize_keyword_value(raw_keyword)
        if not keyword:
            continue
        if len(keyword) > 255:
            raise HTTPException(status_code=422, detail=f"Keyword too long: {keyword[:32]}")
        normalized_inputs.append(keyword)
    return dedupe_keywords_case_insensitive(normalized_inputs)


async def _existing_keyword_identity_map(db: AsyncSession) -> dict[str, str]:
    """identity_key -> keyword id。优先用持久化列 keyword_identity，与库唯一约束一致。"""
    result = await db.execute(select(Keyword.id, Keyword.keyword, Keyword.keyword_identity))
    out: dict[str, str] = {}
    for keyword_id, keyword, stored_identity in result.all():
        if not keyword:
            continue
        key = (stored_identity or "").strip() or keyword_identity_key(str(keyword))
        out[key] = str(keyword_id)
    return out


async def _build_keyword_record(
    keyword_value: str,
    *,
    description: str | None,
    match_type: str,
    match_scope: str,
    case_sensitive: bool,
    notify: bool,
    notify_email: bool,
    color: str,
    enabled: bool,
    manual_equivalent_terms: list[str] | None = None,
    include_auto_equivalent_terms: bool = True,
) -> Keyword:
    manual_norm = normalize_manual_equivalent_terms(
        manual_equivalent_terms or [],
        main_keyword=keyword_value,
    )
    eq = await compute_stored_equivalent_terms(
        keyword_value,
        match_type=match_type,
        manual_terms=manual_norm,
        include_auto=include_auto_equivalent_terms,
    )
    return Keyword(
        keyword=keyword_value,
        keyword_identity=keyword_identity_key(keyword_value),
        description=description,
        match_type=match_type,
        match_scope=match_scope,
        case_sensitive=case_sensitive,
        notify=notify,
        notify_email=notify_email,
        color=color,
        enabled=enabled,
        manual_equivalent_terms=manual_norm,
        include_auto_equivalent_terms=include_auto_equivalent_terms,
        equivalent_terms=eq,
    )


@router.post("", response_model=KeywordResponse)
async def create_keyword(
    keyword_data: KeywordCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_async_db),
):
    """Create a new keyword."""
    keyword_value = normalize_keyword_value(keyword_data.keyword)
    if not keyword_value:
        raise HTTPException(status_code=422, detail="Keyword is required")

    existing = await _existing_keyword_identity_map(db)
    if keyword_identity_key(keyword_value) in existing:
        raise HTTPException(
            status_code=409,
            detail=f"已存在相同搜索词（忽略大小写）：{keyword_value}",
        )

    keyword = await _build_keyword_record(
        keyword_value,
        description=keyword_data.description,
        match_type=keyword_data.match_type,
        match_scope=keyword_data.match_scope,
        case_sensitive=keyword_data.case_sensitive,
        notify=keyword_data.notify,
        notify_email=keyword_data.notify_email,
        color=keyword_data.color,
        enabled=keyword_data.enabled,
        manual_equivalent_terms=list(keyword_data.manual_equivalent_terms or []),
        include_auto_equivalent_terms=keyword_data.include_auto_equivalent_terms,
    )
    db.add(keyword)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"已存在相同搜索词（忽略大小写）：{keyword_value}",
        ) from None
    await db.refresh(keyword)
    _enqueue_keyword_match_refresh(background_tasks)
    return keyword


@router.post("/batch", response_model=KeywordBatchCreateResponse)
async def create_keywords_batch(
    keyword_data: KeywordBatchCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_async_db),
):
    """Create multiple keywords with shared settings."""
    normalized_keywords, skipped_keywords = _normalize_batch_keywords(keyword_data.keywords)
    if not normalized_keywords:
        raise HTTPException(status_code=422, detail="At least one valid keyword is required")

    existing_identity_map = await _existing_keyword_identity_map(db)
    created_items: list[Keyword] = []
    for keyword_value in normalized_keywords:
        identity = keyword_identity_key(keyword_value)
        if identity in existing_identity_map:
            skipped_keywords.append(keyword_value)
            continue

        keyword = await _build_keyword_record(
            keyword_value,
            description=keyword_data.description,
            match_type=keyword_data.match_type,
            match_scope=keyword_data.match_scope,
            case_sensitive=keyword_data.case_sensitive,
            notify=keyword_data.notify,
            notify_email=keyword_data.notify_email,
            color=keyword_data.color,
            enabled=keyword_data.enabled,
            manual_equivalent_terms=list(keyword_data.manual_equivalent_terms or []),
            include_auto_equivalent_terms=keyword_data.include_auto_equivalent_terms,
        )
        db.add(keyword)
        created_items.append(keyword)
        existing_identity_map[identity] = "pending"

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="批量创建时发现与已有词冲突（忽略大小写），请刷新后重试。",
        ) from None
    for keyword in created_items:
        await db.refresh(keyword)

    _enqueue_keyword_match_refresh(background_tasks)
    return KeywordBatchCreateResponse(
        items=created_items,
        total=len(created_items),
        skipped_keywords=skipped_keywords,
    )


@router.get("", response_model=KeywordListResponse)
async def list_keywords(
    enabled: bool = None,
    db: AsyncSession = Depends(get_async_db)
):
    """List all keywords.

    不使用进程内 TTL 缓存：多 worker / 多进程下缓存无法跨进程失效，会导致 PATCH 已更新等价词
    但 GET 列表仍返回旧数据。
    """
    query = select(Keyword)
    count_query = select(func.count(Keyword.id))
    
    if enabled is not None:
        query = query.filter(Keyword.enabled == enabled)
        count_query = count_query.filter(Keyword.enabled == enabled)
    
    query = query.order_by(Keyword.created_at.desc())
    
    result = await db.execute(query)
    keywords = result.scalars().all()
    
    total_result = await db.execute(count_query)
    total = total_result.scalar()
    
    return KeywordListResponse(items=keywords, total=total).model_dump(mode="json")


@router.patch("/batch", response_model=KeywordBatchUpdateResponse)
async def update_keywords_batch(
    keyword_data: KeywordBatchUpdate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_async_db),
):
    """Update shared properties for multiple keywords."""
    update_data = keyword_data.model_dump(exclude_unset=True, exclude={"keyword_ids"})
    if not update_data:
        raise HTTPException(status_code=422, detail="No fields provided for batch update")

    result = await db.execute(
        select(Keyword).filter(Keyword.id.in_([str(keyword_id) for keyword_id in keyword_data.keyword_ids]))
    )
    items = result.scalars().all()
    for item in items:
        for field, value in update_data.items():
            setattr(item, field, value)

    if "match_type" in update_data:
        for item in items:
            item.equivalent_terms = await compute_stored_equivalent_terms(
                str(item.keyword),
                match_type=_enum_value(item.match_type),
                manual_terms=list(item.manual_equivalent_terms or []),
                include_auto=_include_auto_bool(item),
            )
            flag_modified(item, "equivalent_terms")

    await db.commit()
    for item in items:
        await db.refresh(item)

    _enqueue_keyword_match_refresh(background_tasks)
    return KeywordBatchUpdateResponse(items=items, total=len(items))


@router.get("/{keyword_id}", response_model=KeywordResponse)
async def get_keyword(
    keyword_id: UUID,
    db: AsyncSession = Depends(get_async_db)
):
    """Get a specific keyword by ID."""
    result = await db.execute(select(Keyword).filter(Keyword.id == keyword_id))
    keyword = result.scalar_one_or_none()
    
    if not keyword:
        raise HTTPException(status_code=404, detail="Keyword not found")
    
    return keyword


@router.patch("/{keyword_id}", response_model=KeywordResponse)
async def update_keyword(
    keyword_id: UUID,
    keyword_data: KeywordUpdate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_async_db),
):
    """Update a keyword."""
    result = await db.execute(select(Keyword).filter(Keyword.id == keyword_id))
    keyword = result.scalar_one_or_none()
    
    if not keyword:
        raise HTTPException(status_code=404, detail="Keyword not found")
    
    update_data = keyword_data.model_dump(exclude_unset=True)
    update_data.pop("equivalent_terms", None)

    if "keyword" in update_data:
        keyword_value = normalize_keyword_value(update_data["keyword"])
        if not keyword_value:
            raise HTTPException(status_code=422, detail="Keyword is required")
        existing = await _existing_keyword_identity_map(db)
        owner_id = existing.get(keyword_identity_key(keyword_value))
        if owner_id and owner_id != str(keyword_id):
            raise HTTPException(
                status_code=409,
                detail=f"已存在相同搜索词（忽略大小写）：{keyword_value}",
            )
        update_data["keyword"] = keyword_value

    for field, value in update_data.items():
        if field == "manual_equivalent_terms":
            continue
        setattr(keyword, field, value)

    if "keyword" in update_data:
        keyword.keyword_identity = keyword_identity_key(str(keyword.keyword))

    if "manual_equivalent_terms" in update_data:
        keyword.manual_equivalent_terms = normalize_manual_equivalent_terms(
            update_data["manual_equivalent_terms"] or [],
            main_keyword=str(keyword.keyword),
        )
        flag_modified(keyword, "manual_equivalent_terms")

    if any(
        k in update_data
        for k in ("keyword", "match_type", "manual_equivalent_terms", "include_auto_equivalent_terms")
    ):
        keyword.equivalent_terms = await compute_stored_equivalent_terms(
            str(keyword.keyword),
            match_type=_enum_value(keyword.match_type),
            manual_terms=list(keyword.manual_equivalent_terms or []),
            include_auto=_include_auto_bool(keyword),
        )
        flag_modified(keyword, "equivalent_terms")
    
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="与已有搜索词冲突（忽略大小写），请刷新后重试。",
        ) from None
    await db.refresh(keyword)
    _enqueue_keyword_match_refresh(background_tasks)
    return keyword


@router.delete("/{keyword_id}")
async def delete_keyword(
    keyword_id: UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_async_db),
):
    """Delete a keyword."""
    result = await db.execute(select(Keyword).filter(Keyword.id == keyword_id))
    keyword = result.scalar_one_or_none()
    
    if not keyword:
        raise HTTPException(status_code=404, detail="Keyword not found")
    
    await db.delete(keyword)
    await db.commit()
    _enqueue_keyword_match_refresh(background_tasks)

    return {"message": "Keyword deleted successfully"}
