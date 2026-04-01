"""API routes for category management."""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_async_db
from app.models import Category, Source
from app.schemas.category import (
    CategoryCreate,
    CategoryUpdate,
    CategoryResponse,
)
from app.utils.ttl_cache import TTLCache

router = APIRouter()
_category_cache = TTLCache(ttl_seconds=30)


async def _load_source_counts(
    db: AsyncSession,
    *,
    category_ids: list[str] | None = None,
) -> dict[str, int]:
    query = (
        select(Source.category_id, func.count(Source.id))
        .filter(Source.category_id.is_not(None))
        .group_by(Source.category_id)
    )
    if category_ids:
        query = query.filter(Source.category_id.in_(category_ids))

    result = await db.execute(query)
    return {
        str(category_id): int(count)
        for category_id, count in result.all()
        if category_id
    }


def _build_category_response(
    category: Category,
    *,
    source_counts: dict[str, int],
    flat: bool,
) -> CategoryResponse:
    children = []
    if not flat:
        loaded_children = category.__dict__.get("children", [])
        sorted_children = sorted(
            loaded_children,
            key=lambda child: (child.sort_order, child.name.lower()),
        )
        children = [
            _build_category_response(child, source_counts=source_counts, flat=False)
            for child in sorted_children
        ]

    return CategoryResponse(
        id=category.id,
        name=category.name,
        description=category.description,
        color=category.color,
        icon=category.icon,
        parent_id=category.parent_id,
        sort_order=category.sort_order,
        created_at=category.created_at,
        updated_at=category.updated_at,
        source_count=source_counts.get(str(category.id), 0),
        children=children,
    )


def _invalidate_category_cache() -> None:
    _category_cache.invalidate()


@router.post("", response_model=CategoryResponse)
async def create_category(
    category_data: CategoryCreate,
    db: AsyncSession = Depends(get_async_db)
):
    """Create a new category."""
    category = Category(
        name=category_data.name,
        description=category_data.description,
        color=category_data.color,
        icon=category_data.icon,
        parent_id=category_data.parent_id,
        sort_order=category_data.sort_order,
    )
    db.add(category)
    await db.commit()
    await db.refresh(category)
    _invalidate_category_cache()
    return _build_category_response(category, source_counts={}, flat=True)


@router.get("", response_model=List[CategoryResponse])
async def list_categories(
    flat: bool = False,
    db: AsyncSession = Depends(get_async_db)
):
    """List all categories. If flat=False, returns a tree structure."""
    cache_key = f"categories:{'flat' if flat else 'tree'}"
    cached = _category_cache.get(cache_key)
    if cached is not None:
        return cached

    result = await db.execute(
        select(Category)
        .options(selectinload(Category.children))
        .order_by(Category.sort_order, Category.name)
    )
    categories = result.scalars().all()

    category_ids = [str(category.id) for category in categories]
    source_counts = await _load_source_counts(db, category_ids=category_ids)

    if flat:
        payload = [
            _build_category_response(category, source_counts=source_counts, flat=True)
            for category in categories
        ]
        return _category_cache.set(cache_key, payload)

    root_categories = [category for category in categories if category.parent_id is None]
    payload = [
        _build_category_response(category, source_counts=source_counts, flat=False)
        for category in root_categories
    ]
    return _category_cache.set(cache_key, payload)


@router.get("/{category_id}", response_model=CategoryResponse)
async def get_category(
    category_id: UUID,
    db: AsyncSession = Depends(get_async_db)
):
    """Get a specific category by ID."""
    result = await db.execute(
        select(Category)
        .options(selectinload(Category.children))
        .filter(Category.id == category_id)
    )
    category = result.scalar_one_or_none()
    
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    child_ids = [str(child.id) for child in category.children]
    source_counts = await _load_source_counts(
        db,
        category_ids=[str(category.id), *child_ids],
    )
    return _build_category_response(category, source_counts=source_counts, flat=False)


@router.patch("/{category_id}", response_model=CategoryResponse)
async def update_category(
    category_id: UUID,
    category_data: CategoryUpdate,
    db: AsyncSession = Depends(get_async_db)
):
    """Update a category."""
    result = await db.execute(select(Category).filter(Category.id == category_id))
    category = result.scalar_one_or_none()
    
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    
    # Update only provided fields
    update_data = category_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(category, field, value)
    
    await db.commit()
    await db.refresh(category)
    _invalidate_category_cache()
    source_counts = await _load_source_counts(db, category_ids=[str(category.id)])
    return _build_category_response(category, source_counts=source_counts, flat=True)


@router.delete("/{category_id}")
async def delete_category(
    category_id: UUID,
    db: AsyncSession = Depends(get_async_db)
):
    """Delete a category."""
    result = await db.execute(select(Category).filter(Category.id == category_id))
    category = result.scalar_one_or_none()
    
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    
    # Check if category has sources
    count_result = await db.execute(
        select(func.count(Source.id)).filter(Source.category_id == category_id)
    )
    source_count = count_result.scalar()
    
    if source_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete category with {source_count} sources. Move or delete sources first."
        )
    
    await db.delete(category)
    await db.commit()
    _invalidate_category_cache()
    return {"message": "Category deleted successfully"}
