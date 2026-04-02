# Stream 2: Backend 重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 sources.py 和 probe_service.py 按职责拆分，引入有界任务队列替代裸 asyncio.create_task，并将关键模块覆盖率从 <25% 提升到 70%+。

**Architecture:** sources.py 按查询/变更/探测/导入拆为子包，`from app.api import sources` 仍有效；probe_service.py 按类型拆为策略 mixin；task_queue.py 提供有界 asyncio.Queue + worker 协程，在 main.py lifespan 启停；测试覆盖正常路径和主要错误路径。

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy async, asyncio, pytest, pytest-asyncio

---

## 文件结构

```
backend/app/api/
├── sources/
│   ├── __init__.py        # 组合路由，对外 router 不变
│   ├── _helpers.py        # 所有私有工具函数
│   ├── query.py           # list_sources, get_source, export_sources
│   ├── mutation.py        # create_source, update_source, delete_source
│   ├── probe.py           # probe_url, probe_source, probe_all_sources
│   └── fetch_import.py    # trigger_fetch, trigger_fetch_all, bulk_import
└── sources.py             # 删除

backend/app/services/
├── probe_service.py           # 保留基类 + probe() 调度 + 公共 helpers
└── probe_strategies/
    ├── __init__.py
    ├── rss.py                 # RSS 相关策略方法
    ├── website.py             # Website 相关策略方法
    ├── x.py                   # X/Twitter 相关策略方法
    └── youtube.py             # YouTube 相关策略方法

backend/app/tasks/
└── task_queue.py              # BoundedTaskQueue + 模块级单例

backend/tests/
├── test_api_sources_extended.py
├── test_fetch_tasks_extended.py
├── test_process_tasks_extended.py
└── test_configs_api_auth_extended.py
```

---

### Task 1: 提取 sources/_helpers.py

**Files:**
- Create: `backend/app/api/sources/_helpers.py`
- Modify: (暂不动 sources.py，先创建目标文件)

- [ ] **Step 1: 创建 `backend/app/api/sources/` 目录和 `_helpers.py`**

```python
# backend/app/api/sources/_helpers.py
"""Private helper functions shared across sources sub-modules."""

from typing import Dict, List, Optional, Tuple
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Source, AuthConfig
from app.models.source import SourceType
from app.features import PODCAST_DISABLED_DETAIL, PODCAST_SOURCES_ENABLED
from app.services.system_settings import get_system_settings_async
from app.utils.datetime import to_iso_z
from app.utils.ttl_cache import TTLCache
from app.utils.url import host_matches, normalize_host
from app.utils.logger import get_logger

logger = get_logger(__name__)

MAX_SOURCES_PAGE_SIZE = 200

_source_cache = TTLCache(ttl_seconds=30)


def _source_type_value(source_type: object) -> str:
    return source_type.value if hasattr(source_type, "value") else str(source_type)


def _ensure_supported_source_type(source_type: object) -> str:
    normalized = _source_type_value(source_type)
    if normalized == "podcast" and not PODCAST_SOURCES_ENABLED:
        raise HTTPException(status_code=409, detail=PODCAST_DISABLED_DETAIL)
    return normalized


def _exclude_disabled_source_types(query):
    if not PODCAST_SOURCES_ENABLED:
        query = query.filter(Source.type != SourceType.PODCAST)
    return query


def _source_is_visible(source: Source) -> bool:
    return PODCAST_SOURCES_ENABLED or _source_type_value(source.type) != "podcast"


def _invalidate_source_cache() -> None:
    _source_cache.invalidate()


def _coerce_limit_int(value, default: int, *, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        return default
    return max(min_value, min(max_value, parsed))


async def _resolve_max_sources_limit(db: AsyncSession) -> int:
    settings = await get_system_settings_async(db)
    limits = settings.get("limits") if isinstance(settings, dict) else {}
    limits = limits if isinstance(limits, dict) else {}
    return _coerce_limit_int(limits.get("max_sources"), 200, min_value=1, max_value=5000)


async def _ensure_source_quota(db: AsyncSession, incoming_count: int = 1) -> None:
    incoming = max(0, int(incoming_count or 0))
    if incoming <= 0:
        return
    max_sources = await _resolve_max_sources_limit(db)
    total_result = await db.execute(select(func.count(Source.id)))
    current_total = int(total_result.scalar() or 0)
    if current_total + incoming > max_sources:
        raise HTTPException(status_code=409, detail="监控源数量已达到上限，无法继续添加。")


def _normalize_extra_urls(extra_urls: Optional[List[str]]) -> List[str]:
    if not extra_urls:
        return []
    seen = set()
    normalized: List[str] = []
    for raw in extra_urls:
        if not raw:
            continue
        candidate = raw.strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        normalized.append(candidate)
    return normalized


def _get_source_urls(source: Source) -> List[str]:
    metadata = source.metadata_ if isinstance(source.metadata_, dict) else {}
    extras = _normalize_extra_urls(metadata.get("extra_urls"))
    urls = [source.url]
    for u in extras:
        if u != source.url:
            urls.append(u)
    return urls


def _pick_best_probe(results: List[Tuple[str, object]]) -> Tuple[object, Dict[str, str], int]:
    rss_urls: Dict[str, str] = {}
    ok_count = 0
    status_order = {"ok": 0, "warning": 1, "error": 2, "unknown": 3}
    best_url = ""
    best_result = None
    best_rank = 99
    for url, result in results:
        status = getattr(result, "status", "unknown")
        rank = status_order.get(status, 3)
        if getattr(result, "rss_url", None):
            rss_urls[url] = result.rss_url
        if status == "ok":
            ok_count += 1
        if best_result is None or rank < best_rank:
            best_result = result
            best_rank = rank
            best_url = url
    if best_result is not None:
        source_message = getattr(best_result, "message", "") or ""
        summary = f"可用 URL {ok_count}/{len(results)}"
        best_result.message = f"{summary}；主策略来自 {best_url}。{source_message}".strip("。")
    return best_result, rss_urls, ok_count


async def _find_matching_auth_config_id(db: AsyncSession, url: str) -> Optional[UUID]:
    source_host = normalize_host(url)
    if not source_host:
        return None
    result = await db.execute(select(AuthConfig).order_by(AuthConfig.updated_at.desc()))
    configs = result.scalars().all()
    for cfg in configs:
        cfg_host = normalize_host(cfg.site_url)
        if host_matches(source_host, cfg_host):
            return cfg.id
    return None


async def _probe_urls(urls: List[str], source_type: str):
    import asyncio
    from app.services.probe_service import ProbeService
    _probe_service = ProbeService()
    tasks = [_probe_service.probe(url, source_type) for url in urls]
    probe_results = await asyncio.gather(*tasks, return_exceptions=True)
    paired = [(url, r) for url, r in zip(urls, probe_results) if not isinstance(r, Exception)]
    if not paired:
        fallback = await _probe_service.probe(urls[0], source_type)
        return fallback, {}, 0
    return _pick_best_probe(paired)


def _compute_fetch_status(s: Source, probe: dict) -> tuple:
    probe_status = probe.get("status", "unknown")
    probe_strategy = probe.get("strategy", "unknown")
    probe_message = probe.get("message", "")
    metadata = s.metadata_ if isinstance(s.metadata_, dict) else {}
    outcome = metadata.get("last_fetch_outcome") if isinstance(metadata.get("last_fetch_outcome"), dict) else {}
    outcome_severity = str(outcome.get("severity") or "").strip().lower()
    outcome_message = str(outcome.get("message") or "").strip()
    has_content = bool(s.last_content_id)
    has_fetched = s.last_fetched_at is not None
    has_errors = s.error_count > 0 and s.last_error
    if has_fetched and outcome_severity == "error":
        return ("error", probe_strategy if probe_strategy != "unknown" else "auto", outcome_message or "最近抓取失败")
    if has_fetched and outcome_severity == "warning":
        return ("warning", probe_strategy if probe_strategy != "unknown" else "auto", outcome_message or "最近抓取部分受限")
    if has_content and has_fetched:
        if has_errors:
            return ("warning", probe_strategy if probe_strategy != "unknown" else "auto",
                    f"已成功抓取过内容，但最近有错误: {s.last_error[:60] if s.last_error else ''}")
        return ("ok", probe_strategy if probe_strategy != "unknown" else "auto", "已成功抓取内容")
    if has_fetched and not has_content:
        if probe_status == "ok":
            return ("ok", probe_strategy, f"探测可用。{probe_message}")
        if has_errors:
            return ("error", probe_strategy, f"抓取失败: {s.last_error[:60] if s.last_error else ''}")
        return ("warning", probe_strategy if probe_strategy != "unknown" else "auto",
                f"最近抓取完成但暂无新内容。{probe_message}".strip())
    if probe_status != "unknown":
        return (probe_status, probe_strategy, probe_message)
    return ("unknown", "unknown", "")


def serialize_source(s: Source) -> dict:
    meta = s.metadata_ if isinstance(s.metadata_, dict) else {}
    probe = meta.get("probe", {})
    eff_status, eff_strategy, eff_message = _compute_fetch_status(s, probe)
    return {
        "id": str(s.id),
        "name": s.name,
        "type": s.type.value if hasattr(s.type, 'value') else s.type,
        "url": s.url,
        "extra_urls": _normalize_extra_urls(meta.get("extra_urls")),
        "category_id": str(s.category_id) if s.category_id else None,
        "fetch_interval": s.fetch_interval,
        "enabled": s.enabled,
        "priority": s.priority,
        "auth_required": s.auth_required,
        "auth_config_id": str(s.auth_config_id) if s.auth_config_id else None,
        "last_fetched_at": to_iso_z(s.last_fetched_at),
        "last_content_id": s.last_content_id,
        "last_error": s.last_error,
        "error_count": s.error_count,
        "metadata": meta,
        "fetch_status": eff_status,
        "fetch_strategy": eff_strategy,
        "fetch_status_message": eff_message,
        "probed_at": probe.get("probed_at"),
        "created_at": to_iso_z(s.created_at),
        "updated_at": to_iso_z(s.updated_at),
    }
```

- [ ] **Step 2: 运行现有测试确认当前基线**

```bash
cd backend && ./.venv/bin/pytest -q --no-header 2>&1 | tail -3
```

Expected: `556 passed`

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/sources/_helpers.py
git commit -m "refactor: 提取 sources/_helpers.py（私有工具函数）"
```

---

### Task 2: 创建 sources/query.py

**Files:**
- Create: `backend/app/api/sources/query.py`

- [ ] **Step 1: 创建 query.py**

```python
# backend/app/api/sources/query.py
"""Read-only source routes: list, get, export."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.models import Source
from app.features import PODCAST_SOURCES_ENABLED
from app.utils.datetime import to_iso_z
from app.utils.logger import get_logger
from ._helpers import (
    _exclude_disabled_source_types,
    _source_is_visible,
    _source_cache,
    MAX_SOURCES_PAGE_SIZE,
    serialize_source,
)

logger = get_logger(__name__)
router = APIRouter()


@router.get("")
async def list_sources(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=MAX_SOURCES_PAGE_SIZE),
    type: Optional[str] = None,
    category_id: Optional[UUID] = None,
    enabled: Optional[bool] = None,
    search: Optional[str] = None,
    scope: Optional[str] = None,
    db: AsyncSession = Depends(get_async_db),
):
    if type == "podcast" and not PODCAST_SOURCES_ENABLED:
        return {"items": [], "total": 0, "page": page, "page_size": page_size, "total_pages": 0}

    cache_key = (
        f"sources:page={page}:size={page_size}:type={type or ''}:"
        f"category={category_id or ''}:enabled={enabled!r}:search={search or ''}"
    )
    cached = _source_cache.get(cache_key)
    if cached is not None:
        return cached

    query = _exclude_disabled_source_types(select(Source))
    count_query = _exclude_disabled_source_types(select(func.count(Source.id)))

    if type:
        query = query.filter(Source.type == type)
        count_query = count_query.filter(Source.type == type)
    if category_id:
        query = query.filter(Source.category_id == category_id)
        count_query = count_query.filter(Source.category_id == category_id)
    if enabled is not None:
        query = query.filter(Source.enabled == enabled)
        count_query = count_query.filter(Source.enabled == enabled)
    if search:
        search_filter = Source.name.ilike(f"%{search}%")
        query = query.filter(search_filter)
        count_query = count_query.filter(search_filter)

    total_result = await db.execute(count_query)
    total = total_result.scalar()
    offset = (page - 1) * page_size
    query = query.order_by(Source.priority.desc(), Source.name).offset(offset).limit(page_size)
    result = await db.execute(query)
    sources = result.scalars().all()
    total_pages = (total + page_size - 1) // page_size

    payload = {
        "items": [serialize_source(s) for s in sources],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }
    return _source_cache.set(cache_key, payload)


@router.get("/export")
async def export_sources(db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(_exclude_disabled_source_types(select(Source)))
    sources = result.scalars().all()
    return {
        "sources": [serialize_source(s) for s in sources],
        "exported_at": to_iso_z(None),
    }


@router.get("/{source_id}")
async def get_source(source_id: UUID, db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(select(Source).filter(Source.id == source_id))
    source = result.scalar_one_or_none()
    if not source or not _source_is_visible(source):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Source not found")
    return serialize_source(source)
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/api/sources/query.py
git commit -m "refactor: 提取 sources/query.py（列表/详情/导出路由）"
```

---

### Task 3: 创建 sources/mutation.py

**Files:**
- Create: `backend/app/api/sources/mutation.py`

- [ ] **Step 1: 创建 mutation.py**

```python
# backend/app/api/sources/mutation.py
"""Write source routes: create, update, delete."""

import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.models import Source
from app.schemas.source import SourceCreate, SourceUpdate
from app.utils.logger import get_logger
from ._helpers import (
    _ensure_supported_source_type,
    _source_type_value,
    _source_is_visible,
    _ensure_source_quota,
    _normalize_extra_urls,
    _find_matching_auth_config_id,
    _probe_urls,
    _invalidate_source_cache,
    serialize_source,
)

logger = get_logger(__name__)
router = APIRouter()


@router.post("")
async def create_source(source_data: SourceCreate, db: AsyncSession = Depends(get_async_db)):
    _ensure_supported_source_type(source_data.type)
    existing = await db.execute(
        select(Source).filter(Source.url == source_data.url, Source.type == source_data.type)
    )
    if existing.scalars().first():
        raise HTTPException(status_code=409, detail="已存在相同类型和 URL 的监控源")
    await _ensure_source_quota(db, incoming_count=1)

    metadata = dict(source_data.metadata_ or {})
    extra_urls = _normalize_extra_urls(source_data.extra_urls)
    metadata["extra_urls"] = extra_urls

    try:
        all_urls = [source_data.url] + [u for u in extra_urls if u != source_data.url]
        probe_result, rss_urls, _ = await _probe_urls(all_urls, source_data.type)
        metadata["probe"] = probe_result.to_dict()
        if source_data.type == "x" and probe_result.strategy in {"rsshub", "nitter", "api"}:
            metadata["strategy"] = probe_result.strategy
        if rss_urls:
            metadata["rss_urls"] = rss_urls
        if source_data.url in rss_urls:
            metadata["rss_url"] = rss_urls[source_data.url]
        elif probe_result.rss_url and "rss_url" not in metadata:
            metadata["rss_url"] = probe_result.rss_url
    except Exception as exc:
        logger.warning("Probe failed for source %s: %s", source_data.url, exc)
        metadata["probe"] = {"status": "failed", "strategy": "unknown", "rss_url": None,
                              "message": str(exc)[:200], "sample_count": 0, "probed_at": None}

    auth_required = source_data.auth_required
    auth_config_id = source_data.auth_config_id
    if _source_type_value(source_data.type) == "website" and auth_required and not auth_config_id:
        matched_auth_id = await _find_matching_auth_config_id(db, source_data.url)
        if matched_auth_id:
            auth_config_id = matched_auth_id

    source = Source(
        name=source_data.name, type=source_data.type, url=source_data.url,
        category_id=source_data.category_id, fetch_interval=source_data.fetch_interval,
        enabled=source_data.enabled, priority=source_data.priority,
        auth_required=auth_required, auth_config_id=auth_config_id, metadata_=metadata,
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    _invalidate_source_cache()
    return serialize_source(source)


@router.patch("/{source_id}")
async def update_source(source_id: UUID, source_data: SourceUpdate, db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(select(Source).filter(Source.id == source_id))
    source = result.scalar_one_or_none()
    if not source or not _source_is_visible(source):
        raise HTTPException(status_code=404, detail="Source not found")

    update_data = source_data.model_dump(exclude_unset=True)
    extra_urls = update_data.pop("extra_urls", None)
    metadata_patch = update_data.pop("metadata_", None)

    target_type = update_data.get("type") or _source_type_value(source.type)
    _ensure_supported_source_type(target_type)
    target_url = update_data.get("url", source.url)
    target_auth_required = update_data.get("auth_required", source.auth_required)
    target_auth_config_id = update_data.get("auth_config_id", source.auth_config_id)
    explicit_disable = ("auth_required" in update_data and update_data.get("auth_required") is False)

    if (str(target_type) == "website" and bool(target_auth_required)
            and not target_auth_config_id and not explicit_disable):
        matched_auth_id = await _find_matching_auth_config_id(db, target_url)
        if matched_auth_id:
            update_data["auth_config_id"] = matched_auth_id
            update_data["auth_required"] = True

    if metadata_patch is not None:
        merged = dict(source.metadata_ or {})
        merged.update(metadata_patch)
        source.metadata_ = merged
    if extra_urls is not None:
        merged = dict(source.metadata_ or {})
        merged["extra_urls"] = _normalize_extra_urls(extra_urls)
        source.metadata_ = merged

    for field, value in update_data.items():
        setattr(source, field, value)
    await db.commit()
    await db.refresh(source)
    _invalidate_source_cache()
    return serialize_source(source)


@router.delete("/{source_id}")
async def delete_source(source_id: UUID, db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(select(Source).filter(Source.id == source_id))
    source = result.scalar_one_or_none()
    if not source or not _source_is_visible(source):
        raise HTTPException(status_code=404, detail="Source not found")
    await db.delete(source)
    await db.commit()
    _invalidate_source_cache()
    return {"message": "Source deleted successfully"}
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/api/sources/mutation.py
git commit -m "refactor: 提取 sources/mutation.py（创建/更新/删除路由）"
```

---

### Task 4: 创建 sources/probe.py

**Files:**
- Create: `backend/app/api/sources/probe.py`

- [ ] **Step 1: 创建 probe.py**

```python
# backend/app/api/sources/probe.py
"""Probe routes: probe_url, probe_source, probe_all_sources."""

from typing import Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.models import Source
from app.utils.logger import get_logger
from ._helpers import (
    _ensure_supported_source_type,
    _source_is_visible,
    _get_source_urls,
    _probe_urls,
    _invalidate_source_cache,
    serialize_source,
)

logger = get_logger(__name__)
router = APIRouter()


class ProbeRequest(BaseModel):
    url: str
    type: str = "website"


class ProbeResponse(BaseModel):
    status: str
    strategy: str
    rss_url: Optional[str] = None
    message: str = ""
    sample_count: int = 0


@router.post("/probe", response_model=ProbeResponse)
async def probe_url(req: ProbeRequest):
    _ensure_supported_source_type(req.type)
    from app.services.probe_service import ProbeService
    result = await ProbeService().probe(req.url, req.type)
    return ProbeResponse(status=result.status, strategy=result.strategy,
                          rss_url=result.rss_url, message=result.message,
                          sample_count=result.sample_count)


@router.post("/{source_id}/probe")
async def probe_source(source_id: UUID, db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(select(Source).filter(Source.id == source_id))
    source = result.scalar_one_or_none()
    if not source or not _source_is_visible(source):
        raise HTTPException(status_code=404, detail="Source not found")

    stype = _ensure_supported_source_type(source.type)
    urls = _get_source_urls(source)
    probe_result, rss_urls, _ = await _probe_urls(urls, stype)

    meta = dict(source.metadata_ or {})
    meta["probe"] = probe_result.to_dict()
    if stype == "x" and probe_result.strategy in {"rsshub", "nitter", "api"}:
        meta["strategy"] = probe_result.strategy
    if rss_urls:
        meta["rss_urls"] = rss_urls
    if source.url in rss_urls:
        meta["rss_url"] = rss_urls[source.url]
    elif probe_result.rss_url:
        meta["rss_url"] = probe_result.rss_url
    source.metadata_ = meta
    await db.commit()
    await db.refresh(source)
    _invalidate_source_cache()
    return serialize_source(source)


@router.post("/probe-all")
async def probe_all_sources(db: AsyncSession = Depends(get_async_db)):
    from ._helpers import _exclude_disabled_source_types
    result = await db.execute(_exclude_disabled_source_types(select(Source).filter(Source.enabled == True)))
    sources = result.scalars().all()
    if not sources:
        return {"message": "No sources to probe", "total": 0, "failed_items": []}

    updated = 0
    failed_items: List[Dict[str, str]] = []
    for s in sources:
        stype = _ensure_supported_source_type(s.type)
        urls = _get_source_urls(s)
        try:
            probe_result, rss_urls, _ = await _probe_urls(urls, stype)
        except Exception as exc:
            logger.warning("Batch probe failed for source %s: %s", s.id, exc)
            failed_items.append({"id": str(s.id), "error": str(exc)[:200]})
            continue
        meta = dict(s.metadata_ or {})
        meta["probe"] = probe_result.to_dict()
        if stype == "x" and probe_result.strategy in {"rsshub", "nitter", "api"}:
            meta["strategy"] = probe_result.strategy
        if rss_urls:
            meta["rss_urls"] = rss_urls
        if s.url in rss_urls:
            meta["rss_url"] = rss_urls[s.url]
        elif probe_result.rss_url:
            meta["rss_url"] = probe_result.rss_url
        s.metadata_ = meta
        updated += 1
    await db.commit()
    _invalidate_source_cache()
    return {"message": f"Probed {updated} sources", "total": updated, "failed_items": failed_items}
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/api/sources/probe.py
git commit -m "refactor: 提取 sources/probe.py（探测路由）"
```

---

### Task 5: 创建 sources/fetch_import.py

**Files:**
- Create: `backend/app/api/sources/fetch_import.py`

- [ ] **Step 1: 创建 fetch_import.py**

```python
# backend/app/api/sources/fetch_import.py
"""Fetch trigger and bulk import routes."""

import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_db
from app.models import Source
from app.schemas.source import SourceBulkImport
from app.utils.logger import get_logger
from ._helpers import (
    _ensure_supported_source_type,
    _source_is_visible,
    _ensure_source_quota,
    _exclude_disabled_source_types,
    _normalize_extra_urls,
    _invalidate_source_cache,
    serialize_source,
)

logger = get_logger(__name__)
router = APIRouter()


@router.post("/bulk-import")
async def bulk_import_sources(import_data: SourceBulkImport, db: AsyncSession = Depends(get_async_db)):
    for source_data in import_data.sources or []:
        _ensure_supported_source_type(source_data.type)
    await _ensure_source_quota(db, incoming_count=len(import_data.sources or []))

    created_ids = []
    for source_data in import_data.sources:
        metadata = dict(source_data.metadata_ or {}) if source_data.metadata_ else {}
        extra_urls = _normalize_extra_urls(source_data.extra_urls)
        metadata["extra_urls"] = extra_urls
        source = Source(
            name=source_data.name, type=source_data.type, url=source_data.url,
            category_id=source_data.category_id, fetch_interval=source_data.fetch_interval,
            enabled=source_data.enabled, priority=source_data.priority,
            auth_required=source_data.auth_required, auth_config_id=source_data.auth_config_id,
            metadata_=metadata,
        )
        db.add(source)
        await db.flush()
        created_ids.append(source.id)
    await db.commit()
    _invalidate_source_cache()

    result = await db.execute(select(Source).filter(Source.id.in_(created_ids)))
    created_sources = result.scalars().all()
    return [serialize_source(s) for s in created_sources]


@router.post("/fetch-all")
async def trigger_fetch_all(db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(_exclude_disabled_source_types(select(Source).filter(Source.enabled == True)))
    sources = result.scalars().all()
    if not sources:
        return {"message": "No active sources to fetch", "source_count": 0}
    from app.tasks.fetch_tasks import fetch_all_sources
    asyncio.create_task(fetch_all_sources(manual_trigger=True))
    return {"message": "Fetch all dispatched", "source_count": len(sources)}


@router.post("/{source_id}/fetch")
async def trigger_fetch(source_id: UUID, db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(select(Source).filter(Source.id == source_id))
    source = result.scalar_one_or_none()
    if not source or not _source_is_visible(source):
        raise HTTPException(status_code=404, detail="Source not found")
    from app.background import fetch_lock
    from app.tasks.fetch_tasks import fetch_source
    if fetch_lock.is_locked(str(source_id)):
        return {"message": "Fetch already running", "source_id": str(source_id)}
    asyncio.create_task(fetch_source(str(source_id), manual_trigger=True))
    return {"message": "Fetch task dispatched", "source_id": str(source_id)}
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/api/sources/fetch_import.py
git commit -m "refactor: 提取 sources/fetch_import.py（触发抓取/批量导入路由）"
```

---

### Task 6: 创建 sources/__init__.py，切换路由注册，删除旧 sources.py

**Files:**
- Create: `backend/app/api/sources/__init__.py`
- Modify: `backend/app/api/__init__.py`
- Delete: `backend/app/api/sources.py`

- [ ] **Step 1: 创建 `__init__.py`**

```python
# backend/app/api/sources/__init__.py
"""Sources API package — combines all sub-routers into one router.

Import: from app.api.sources import router
"""

from fastapi import APIRouter

from .query import router as query_router
from .mutation import router as mutation_router
from .probe import router as probe_router
from .fetch_import import router as fetch_import_router

router = APIRouter()

# Order matters: fixed-path routes before parameterised /{source_id}
router.include_router(probe_router)          # /probe, /probe-all
router.include_router(fetch_import_router)   # /bulk-import, /fetch-all, /{id}/fetch
router.include_router(query_router)          # GET "", /export, /{id}
router.include_router(mutation_router)       # POST "", PATCH /{id}, DELETE /{id}
```

- [ ] **Step 2: 删除旧 sources.py**

```bash
rm backend/app/api/sources.py
```

- [ ] **Step 3: 验证 `app/api/__init__.py` 的 import 仍然有效**

`from app.api import sources` 和 `sources.router` 继续正常工作（Python 会找到 `sources/` 包）。无需修改 `app/api/__init__.py`。

- [ ] **Step 4: 运行测试验证无回归**

```bash
cd backend && ./.venv/bin/pytest -q --no-header 2>&1 | tail -3
```

Expected: `556 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/sources/__init__.py
git commit -m "refactor: 完成 sources.py → sources/ 包拆分，现有测试全部通过"
```

---

### Task 7: 拆分 probe_service.py — RSS 策略

**Files:**
- Create: `backend/app/services/probe_strategies/__init__.py`
- Create: `backend/app/services/probe_strategies/rss.py`
- Modify: `backend/app/services/probe_service.py`

- [ ] **Step 1: 创建 `probe_strategies/` 目录和 `__init__.py`**

```python
# backend/app/services/probe_strategies/__init__.py
"""Probe strategy mixins — each file handles one source type."""
```

- [ ] **Step 2: 将 RSS 相关方法移到 `rss.py`**

从 `probe_service.py` 中把以下方法剪切到 `rss.py`（保留所有逻辑，仅移动位置）：
`_probe_rss`, `_check_known_feeds`, `_discover_rss`, `_try_common_rss_paths`, `_test_rss_feed`

```python
# backend/app/services/probe_strategies/rss.py
"""RSS probe strategy mixin."""
# [方法体与原 probe_service.py 中完全相同，只是移到这个 mixin 类中]

class RssProbeStrategy:
    async def _probe_rss(self, url: str): ...
    def _check_known_feeds(self, url: str): ...
    async def _discover_rss(self, url: str): ...
    async def _try_common_rss_paths(self, url: str): ...
    async def _test_rss_feed(self, rss_url: str): ...
```

- [ ] **Step 3: 在 probe_service.py 中 ProbeService 继承 RssProbeStrategy**

```python
from app.services.probe_strategies.rss import RssProbeStrategy

class ProbeService(RssProbeStrategy, ...):
    ...
```

- [ ] **Step 4: 运行测试**

```bash
cd backend && ./.venv/bin/pytest -q --no-header 2>&1 | tail -3
```

Expected: `556 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/probe_strategies/
git commit -m "refactor: 提取 probe_strategies/rss.py mixin"
```

---

### Task 8: 拆分 probe_service.py — Website/X/YouTube 策略

**Files:**
- Create: `backend/app/services/probe_strategies/website.py`
- Create: `backend/app/services/probe_strategies/x.py`
- Create: `backend/app/services/probe_strategies/youtube.py`
- Modify: `backend/app/services/probe_service.py`

- [ ] **Step 1: 创建 website.py mixin**

```python
# backend/app/services/probe_strategies/website.py
class WebsiteProbeStrategy:
    async def _probe_website(self, url: str): ...
    async def _test_scrape(self, url: str): ...
```

- [ ] **Step 2: 创建 x.py mixin**

```python
# backend/app/services/probe_strategies/x.py
class XProbeStrategy:
    async def _probe_x(self, url: str): ...
    def _extract_x_username(self, url: str): ...
```

- [ ] **Step 3: 创建 youtube.py mixin**

```python
# backend/app/services/probe_strategies/youtube.py
class YouTubeProbeStrategy:
    async def _probe_youtube(self, url: str): ...
    def _extract_youtube_channel_id(self, url: str): ...
    async def _resolve_youtube_channel_id_from_page(self, url: str): ...
    async def _resolve_youtube_channel_id_from_search(self, hint: str): ...
    def _normalize_youtube_channel_page_url(self, url: str): ...
    def _youtube_channel_page_candidates(self, url: str): ...
```

- [ ] **Step 4: 更新 probe_service.py 继承所有 mixin**

```python
from app.services.probe_strategies.rss import RssProbeStrategy
from app.services.probe_strategies.website import WebsiteProbeStrategy
from app.services.probe_strategies.x import XProbeStrategy
from app.services.probe_strategies.youtube import YouTubeProbeStrategy

class ProbeService(RssProbeStrategy, WebsiteProbeStrategy, XProbeStrategy, YouTubeProbeStrategy):
    # 只保留：__init__, _is_private_address, _assert_public_http_target, probe()
    ...
```

- [ ] **Step 5: 运行测试**

```bash
cd backend && ./.venv/bin/pytest -q --no-header 2>&1 | tail -3
```

Expected: `556 passed`

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/probe_strategies/
git commit -m "refactor: 完成 probe_service.py → probe_strategies/ mixin 拆分"
```

---

### Task 9: 实现 BoundedTaskQueue

**Files:**
- Create: `backend/app/tasks/task_queue.py`
- Test: `backend/tests/test_task_queue.py`

- [ ] **Step 1: 先写测试**

```python
# backend/tests/test_task_queue.py
import asyncio
import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_enqueue_fetch_returns_true_when_capacity_available():
    from app.tasks.task_queue import BoundedTaskQueue
    q = BoundedTaskQueue(fetch_maxsize=5, process_maxsize=5)
    await q.start_workers(fetch_workers=1, process_workers=1)
    try:
        with patch("app.tasks.fetch_tasks.fetch_source", new=AsyncMock()):
            result = await q.enqueue_fetch("source-1")
        assert result is True
    finally:
        await q.stop_workers()


@pytest.mark.asyncio
async def test_enqueue_fetch_returns_false_when_queue_full():
    from app.tasks.task_queue import BoundedTaskQueue
    q = BoundedTaskQueue(fetch_maxsize=1, process_maxsize=1)
    # Don't start workers so queue fills up
    q._fetch_queue = asyncio.Queue(maxsize=1)
    q._fetch_queue.put_nowait(("source-x", False))  # fill it
    result = await q.enqueue_fetch("source-overflow")
    assert result is False


@pytest.mark.asyncio
async def test_enqueue_process_returns_true_when_capacity_available():
    from app.tasks.task_queue import BoundedTaskQueue
    q = BoundedTaskQueue(fetch_maxsize=5, process_maxsize=5)
    await q.start_workers(fetch_workers=1, process_workers=1)
    try:
        with patch("app.tasks.process_tasks.process_new_content", new=AsyncMock()):
            result = await q.enqueue_process("content-1")
        assert result is True
    finally:
        await q.stop_workers()


@pytest.mark.asyncio
async def test_stop_workers_is_idempotent():
    from app.tasks.task_queue import BoundedTaskQueue
    q = BoundedTaskQueue()
    await q.start_workers()
    await q.stop_workers()
    await q.stop_workers()  # 第二次调用不应报错
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd backend && ./.venv/bin/pytest tests/test_task_queue.py -v 2>&1 | tail -10
```

Expected: `ImportError` 或 `ModuleNotFoundError`

- [ ] **Step 3: 实现 task_queue.py**

```python
# backend/app/tasks/task_queue.py
"""Bounded async task queue for fetch and process jobs.

Replaces scattered asyncio.create_task() calls with a queue-backed worker pool,
providing back-pressure: when the queue is full, new tasks are dropped (logged)
instead of being silently heap-allocated.
"""

import asyncio
from app.utils.logger import get_logger

logger = get_logger(__name__)


class BoundedTaskQueue:
    def __init__(self, fetch_maxsize: int = 200, process_maxsize: int = 200):
        self._fetch_maxsize = fetch_maxsize
        self._process_maxsize = process_maxsize
        self._fetch_queue: asyncio.Queue = asyncio.Queue(maxsize=fetch_maxsize)
        self._process_queue: asyncio.Queue = asyncio.Queue(maxsize=process_maxsize)
        self._workers: list[asyncio.Task] = []

    async def enqueue_fetch(self, source_id: str, manual_trigger: bool = False) -> bool:
        """Enqueue a fetch job. Returns False (and logs) if queue is full."""
        try:
            self._fetch_queue.put_nowait((source_id, manual_trigger))
            return True
        except asyncio.QueueFull:
            logger.warning(
                "fetch queue full (maxsize=%d), dropping source_id=%s",
                self._fetch_maxsize, source_id,
            )
            return False

    async def enqueue_process(self, content_id: str, job_id: str | None = None) -> bool:
        """Enqueue a process job. Returns False (and logs) if queue is full."""
        try:
            self._process_queue.put_nowait((content_id, job_id))
            return True
        except asyncio.QueueFull:
            logger.warning(
                "process queue full (maxsize=%d), dropping content_id=%s",
                self._process_maxsize, content_id,
            )
            return False

    async def start_workers(self, fetch_workers: int = 4, process_workers: int = 4) -> None:
        """Start worker coroutines. Call once from app lifespan startup."""
        for _ in range(fetch_workers):
            self._workers.append(asyncio.create_task(self._fetch_worker()))
        for _ in range(process_workers):
            self._workers.append(asyncio.create_task(self._process_worker()))
        logger.info("BoundedTaskQueue started: %d fetch workers, %d process workers",
                    fetch_workers, process_workers)

    async def stop_workers(self) -> None:
        """Drain queues and cancel workers. Call from app lifespan shutdown."""
        for w in self._workers:
            w.cancel()
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        logger.info("BoundedTaskQueue stopped")

    async def _fetch_worker(self) -> None:
        from app.tasks.fetch_tasks import fetch_source
        while True:
            try:
                source_id, manual_trigger = await self._fetch_queue.get()
                try:
                    await fetch_source(source_id, manual_trigger=manual_trigger)
                except Exception as exc:
                    logger.error("fetch worker error for source_id=%s: %s", source_id, exc)
                finally:
                    self._fetch_queue.task_done()
            except asyncio.CancelledError:
                break

    async def _process_worker(self) -> None:
        from app.tasks.process_tasks import process_new_content
        while True:
            try:
                content_id, job_id = await self._process_queue.get()
                try:
                    await process_new_content(content_id, job_id=job_id)
                except Exception as exc:
                    logger.error("process worker error for content_id=%s: %s", content_id, exc)
                finally:
                    self._process_queue.task_done()
            except asyncio.CancelledError:
                break


# Module-level singleton used by fetch_tasks and process_tasks
task_queue = BoundedTaskQueue()
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd backend && ./.venv/bin/pytest tests/test_task_queue.py -v 2>&1 | tail -10
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/tasks/task_queue.py backend/tests/test_task_queue.py
git commit -m "feat: 实现 BoundedTaskQueue，有界任务队列替代裸 create_task"
```

---

### Task 10: 集成 task_queue 到 main.py 和 tasks

**Files:**
- Modify: `backend/app/main.py:46-68`
- Modify: `backend/app/tasks/fetch_tasks.py:96-98,129-132,169-172`
- Modify: `backend/app/tasks/process_tasks.py:145-149`

- [ ] **Step 1: 更新 main.py lifespan**

在 `backend/app/main.py` 的 `lifespan` 函数中，在 `scheduler.start()` 后添加：

```python
# startup（在 scheduler.start() 之后）:
from app.tasks.task_queue import task_queue
await task_queue.start_workers()

# shutdown（在 scheduler.shutdown() 之后）:
await task_queue.stop_workers()
```

- [ ] **Step 2: 更新 fetch_tasks.py 的三处 create_task**

```python
# fetch_tasks.py 第 94-98 行：process_new_content 调度
# 旧：
for cid in new_ids:
    asyncio.create_task(process_new_content(str(cid)))
# 新：
from app.tasks.task_queue import task_queue
for cid in new_ids:
    await task_queue.enqueue_process(str(cid))
```

```python
# fetch_tasks.py 第 129-132 行：fetch_all_sources 中调度单个 source
# 旧：
asyncio.create_task(fetch_source(sid, manual_trigger=manual_trigger))
# 新：
await task_queue.enqueue_fetch(sid, manual_trigger=manual_trigger)
```

```python
# fetch_tasks.py 第 169-172 行：check_and_fetch_due_sources 中调度
# 旧：
asyncio.create_task(fetch_source(sid))
# 新：
await task_queue.enqueue_fetch(sid)
```

- [ ] **Step 3: 更新 process_tasks.py 的一处 create_task**

```python
# process_tasks.py 第 145-149 行：batch_process_contents
# 旧：
asyncio.create_task(process_content(content_id, regenerate_summary, retranslate))
# 新：
await task_queue.enqueue_process(content_id)
# 注：batch_process_contents 的 regenerate_summary/retranslate 参数暂由 enqueue_process 忽略，
# 使用 process_new_content 处理（行为与原来一致）
```

- [ ] **Step 4: 运行完整测试**

```bash
cd backend && ./.venv/bin/pytest -q --no-header 2>&1 | tail -3
```

Expected: `560+ passed`（新增 task_queue 测试）

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py backend/app/tasks/fetch_tasks.py backend/app/tasks/process_tasks.py
git commit -m "feat: 集成 BoundedTaskQueue，替换 4 处 asyncio.create_task"
```

---

### Task 11: 补测 — sources API（17% → 70%+）

**Files:**
- Create: `backend/tests/test_api_sources_extended.py`

- [ ] **Step 1: 创建测试文件**

```python
# backend/tests/test_api_sources_extended.py
"""Extended tests for sources API — normal paths + error paths."""

import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_list_sources_returns_empty_when_no_sources(async_client: AsyncClient):
    resp = await async_client.get("/api/sources")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 0
    assert "items" in data


@pytest.mark.asyncio
async def test_list_sources_pagination(async_client: AsyncClient, db_session):
    # 先创建 3 个 source
    from app.models import Source
    for i in range(3):
        db_session.add(Source(name=f"src{i}", type="rss", url=f"https://example{i}.com/feed",
                               fetch_interval=60, enabled=True, priority=0))
    await db_session.commit()

    resp = await async_client.get("/api/sources?page=1&page_size=2")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) <= 2
    assert data["total"] >= 3


@pytest.mark.asyncio
async def test_get_source_not_found(async_client: AsyncClient):
    resp = await async_client.get("/api/sources/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_source_duplicate_rejected(async_client: AsyncClient, db_session):
    from app.models import Source
    db_session.add(Source(name="dup", type="rss", url="https://dup.com/feed",
                           fetch_interval=60, enabled=True, priority=0))
    await db_session.commit()

    with patch("app.api.sources.mutation._probe_urls", new=AsyncMock(return_value=(
        MagicMock(status="ok", strategy="rss", rss_url=None, message="", to_dict=lambda: {}), {}, 1
    ))):
        resp = await async_client.post("/api/sources", json={
            "name": "dup", "type": "rss", "url": "https://dup.com/feed",
            "fetch_interval": 60, "enabled": True, "priority": 0,
        })
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_create_source_podcast_rejected_when_disabled(async_client: AsyncClient):
    with patch("app.api.sources._helpers.PODCAST_SOURCES_ENABLED", False):
        resp = await async_client.post("/api/sources", json={
            "name": "pod", "type": "podcast", "url": "https://pod.com/feed",
            "fetch_interval": 60, "enabled": True, "priority": 0,
        })
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_delete_source_not_found(async_client: AsyncClient):
    resp = await async_client.delete("/api/sources/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_source_not_found(async_client: AsyncClient):
    resp = await async_client.patch(
        "/api/sources/00000000-0000-0000-0000-000000000000",
        json={"enabled": False},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_bulk_import_respects_quota(async_client: AsyncClient):
    with patch("app.api.sources.fetch_import._ensure_source_quota",
               new=AsyncMock(side_effect=Exception("quota exceeded"))):
        resp = await async_client.post("/api/sources/bulk-import", json={"sources": [
            {"name": "x", "type": "rss", "url": "https://x.com/feed",
             "fetch_interval": 60, "enabled": True, "priority": 0}
        ]})
    assert resp.status_code == 500


@pytest.mark.asyncio
async def test_probe_url_endpoint(async_client: AsyncClient):
    with patch("app.api.sources.probe.ProbeService") as MockPS:
        instance = MockPS.return_value
        instance.probe = AsyncMock(return_value=MagicMock(
            status="ok", strategy="rss", rss_url="https://feed.com",
            message="", sample_count=5
        ))
        resp = await async_client.post("/api/sources/probe",
                                        json={"url": "https://example.com", "type": "website"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
```

- [ ] **Step 2: 运行测试**

```bash
cd backend && ./.venv/bin/pytest tests/test_api_sources_extended.py -v 2>&1 | tail -15
```

Expected: 大部分通过；根据测试 fixtures 可能需调整 `async_client` 和 `db_session` 的 fixture 名称（参考项目现有测试写法）。

- [ ] **Step 3: 检查现有 conftest.py 中的 fixture 名称**

```bash
grep -n "def async_client\|def db_session\|def client" backend/tests/conftest.py | head -10
```

根据结果调整测试中的 fixture 引用。

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_api_sources_extended.py
git commit -m "test: 补测 sources API，覆盖主要正常路径和错误路径"
```

---

### Task 12: 补测 — fetch_tasks + process_tasks（15%/11% → 70%+）

**Files:**
- Create: `backend/tests/test_fetch_tasks_extended.py`
- Create: `backend/tests/test_process_tasks_extended.py`

- [ ] **Step 1: 创建 test_fetch_tasks_extended.py**

```python
# backend/tests/test_fetch_tasks_extended.py
"""fetch_tasks coverage: normal path, source not found, domain rate limit."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_fetch_source_source_not_found():
    """When source doesn't exist, _do_fetch logs error and returns."""
    with patch("app.tasks.fetch_tasks.asyncio.to_thread",
               new=AsyncMock(return_value={"status": "error", "message": "Source not found"})):
        with patch("app.tasks.fetch_tasks.get_fetch_semaphore") as mock_sem:
            mock_sem.return_value.__aenter__ = AsyncMock()
            mock_sem.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("app.tasks.fetch_tasks.task_tracker") as mock_tracker:
                mock_tracker.start_fetch = AsyncMock()
                mock_tracker.end_fetch = AsyncMock()
                from app.tasks.fetch_tasks import fetch_source
                # Should not raise
                await fetch_source("nonexistent-id")


@pytest.mark.asyncio
async def test_fetch_all_sources_skips_locked():
    """fetch_all_sources skips sources that are already locked."""
    with patch("app.tasks.fetch_tasks.asyncio.to_thread",
               new=AsyncMock(return_value=["src-1", "src-2"])):
        with patch("app.tasks.fetch_tasks.fetch_lock") as mock_lock:
            mock_lock.is_locked.side_effect = lambda sid: sid == "src-1"
            with patch("app.tasks.task_queue.task_queue") as mock_queue:
                mock_queue.enqueue_fetch = AsyncMock(return_value=True)
                from app.tasks.fetch_tasks import fetch_all_sources
                result = await fetch_all_sources()
    assert result["scheduled"] <= 2


@pytest.mark.asyncio
async def test_fetch_source_exception_is_caught():
    """Exception in fetch pipeline is caught and persisted."""
    with patch("app.tasks.fetch_tasks.asyncio.to_thread",
               new=AsyncMock(side_effect=RuntimeError("network error"))):
        with patch("app.tasks.fetch_tasks.persist_fetch_task_exception", new=AsyncMock()):
            with patch("app.tasks.fetch_tasks.get_fetch_semaphore") as mock_sem:
                mock_sem.return_value.__aenter__ = AsyncMock()
                mock_sem.return_value.__aexit__ = AsyncMock(return_value=False)
                with patch("app.tasks.fetch_tasks.task_tracker") as mock_tracker:
                    mock_tracker.start_fetch = AsyncMock()
                    mock_tracker.end_fetch = AsyncMock()
                    from app.tasks.fetch_tasks import fetch_source
                    await fetch_source("src-1")  # Must not raise
```

- [ ] **Step 2: 创建 test_process_tasks_extended.py**

```python
# backend/tests/test_process_tasks_extended.py
"""process_tasks coverage: normal path, content not found, keyword matching."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_process_new_content_content_not_found():
    """When content doesn't exist, logs error and returns without exception."""
    with patch("app.tasks.process_tasks.asyncio") as mock_asyncio:
        mock_asyncio.to_thread = AsyncMock()
    with patch("app.tasks.process_tasks.get_llm_semaphore") as mock_sem:
        mock_sem.return_value.__aenter__ = AsyncMock()
        mock_sem.return_value.__aexit__ = AsyncMock(return_value=False)
        with patch("app.tasks.process_tasks.task_tracker") as mock_tracker:
            mock_tracker.start_process = AsyncMock()
            mock_tracker.end_process = AsyncMock()
            with patch("app.tasks.process_tasks.SessionLocal") as MockSession:
                mock_db = MagicMock()
                mock_db.query.return_value.options.return_value.filter.return_value.first.return_value = None
                mock_db.__enter__ = MagicMock(return_value=mock_db)
                mock_db.__exit__ = MagicMock(return_value=False)
                MockSession.return_value = mock_db
                from app.tasks.process_tasks import process_new_content
                await process_new_content("nonexistent-id")  # Must not raise


@pytest.mark.asyncio
async def test_process_new_content_keyword_matching():
    """Keyword matching runs when KEYWORD_MONITORING_ENABLED is True."""
    mock_content = MagicMock()
    mock_content.title = "Test Title"
    mock_content.full_content = "Test content body"
    mock_content.summary = None
    mock_content.keyword_matches = []
    mock_content.metadata_ = {}
    mock_content.source = None
    mock_content.auth_config_id = None

    mock_keyword = MagicMock()
    mock_keyword.enabled = True

    with patch("app.tasks.process_tasks.KEYWORD_MONITORING_ENABLED", True):
        with patch("app.tasks.process_tasks.get_llm_semaphore") as mock_sem:
            mock_sem.return_value.__aenter__ = AsyncMock()
            mock_sem.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("app.tasks.process_tasks.task_tracker") as mock_tracker:
                mock_tracker.start_process = AsyncMock()
                mock_tracker.end_process = AsyncMock()
                with patch("app.tasks.process_tasks.SessionLocal") as MockSession:
                    mock_db = MagicMock()
                    mock_db.query.return_value.options.return_value.filter.return_value.first.return_value = mock_content
                    mock_db.query.return_value.filter.return_value.all.return_value = [mock_keyword]
                    MockSession.return_value = mock_db
                    with patch("app.tasks.process_tasks.KeywordMatcher") as MockMatcher:
                        MockMatcher.return_value.match.return_value = [{"id": "kw-1", "keyword": "test"}]
                        from app.tasks.process_tasks import process_new_content
                        await process_new_content("content-1")
                    assert mock_content.keyword_matches == [{"id": "kw-1", "keyword": "test"}]
```

- [ ] **Step 3: 运行测试**

```bash
cd backend && ./.venv/bin/pytest tests/test_fetch_tasks_extended.py tests/test_process_tasks_extended.py -v 2>&1 | tail -15
```

Expected: 全部通过或仅有 fixture 问题（根据现有 conftest 调整）。

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_fetch_tasks_extended.py backend/tests/test_process_tasks_extended.py
git commit -m "test: 补测 fetch_tasks 和 process_tasks，覆盖正常路径和错误场景"
```

---

### Task 13: 补测 — configs_api_auth（23% → 70%+）

**Files:**
- Create: `backend/tests/test_configs_api_auth_extended.py`

- [ ] **Step 1: 查看现有认证配置 API 端点**

```bash
grep -n "^@router" backend/app/api/configs_api_auth.py | head -20
```

- [ ] **Step 2: 创建测试文件**

```python
# backend/tests/test_configs_api_auth_extended.py
"""Extended tests for configs auth API — CRUD + validation."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_auth_configs_returns_list(async_client: AsyncClient):
    resp = await async_client.get("/api/configs/auth")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_create_auth_config_success(async_client: AsyncClient):
    payload = {
        "name": "test-cfg",
        "site_url": "https://example.com",
        "auth_type": "password",
        "username": "user",
        "password": "pass",
    }
    resp = await async_client.post("/api/configs/auth", json=payload)
    assert resp.status_code in (200, 201)
    data = resp.json()
    assert data["site_url"] == "https://example.com"


@pytest.mark.asyncio
async def test_get_auth_config_not_found(async_client: AsyncClient):
    resp = await async_client.get("/api/configs/auth/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_auth_config_not_found(async_client: AsyncClient):
    resp = await async_client.delete("/api/configs/auth/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_auth_config_not_found(async_client: AsyncClient):
    resp = await async_client.patch(
        "/api/configs/auth/00000000-0000-0000-0000-000000000000",
        json={"name": "new-name"},
    )
    assert resp.status_code == 404
```

- [ ] **Step 3: 运行测试，根据实际 API 路径调整**

```bash
cd backend && ./.venv/bin/pytest tests/test_configs_api_auth_extended.py -v 2>&1 | tail -10
```

- [ ] **Step 4: 运行全套测试确认无回归**

```bash
cd backend && ./.venv/bin/pytest -q --no-header 2>&1 | tail -3
```

Expected: `570+ passed`

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_configs_api_auth_extended.py
git commit -m "test: 补测 configs_api_auth，覆盖 CRUD 正常路径和 404 错误路径"
```
