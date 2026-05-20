"""Tasks for fetching content from sources — high-concurrency async engine."""

import asyncio
import random
from uuid import uuid4

from app.background import (
    domain_limiter,
    fetch_lock,
    get_fetch_semaphore,
    task_tracker,
)
from app.config import get_settings
from app.domains.sources.scheduling import (
    effective_due_interval_minutes,
    list_due_source_ids,
)
from app.features import PODCAST_SOURCES_ENABLED
from app.models.source import SourceType
from app.pipeline.coordinator import run_fetch_pipeline
from app.domains.sources.status import persist_fetch_task_exception
from app.utils.logger import get_logger, bind_job_id, restore_job_id
from app.utils.url import normalize_host

logger = get_logger(__name__)
settings = get_settings()


async def fetch_source(source_id: str, manual_trigger: bool = False):
    """Fetch content from a single source. Runs pipeline in a thread."""
    job_id = uuid4().hex
    token = bind_job_id(job_id)
    try:
        logger.info(
            "Starting fetch for source: %s (manual=%s)", source_id, manual_trigger,
            extra={"phase": "fetch", "source_id": source_id},
        )
        sem = get_fetch_semaphore()
        async with sem:
            await task_tracker.start_fetch()
            try:
                await _do_fetch(source_id, manual_trigger, job_id=job_id)
            finally:
                await task_tracker.end_fetch()
    finally:
        restore_job_id(token)


async def _do_fetch(source_id: str, manual_trigger: bool, job_id: str | None = None):
    """执行单源抓取：同步线程查询 + 主循环 async pipeline。"""
    from app.database import SessionLocal
    from app.models import Source

    lock_ttl = 300
    lock_acquired = False
    db = None

    try:
        # --- 阶段 1：在线程中执行同步 DB 查询和锁获取 ---
        def _query_and_lock():
            nonlocal lock_acquired, lock_ttl, db
            db = SessionLocal()
            source = db.query(Source).filter(Source.id == source_id).first()
            if not source:
                return None, "Source not found"

            lock_ttl = max(300, int((source.fetch_interval or 60) * 60))
            _lock_acquired = fetch_lock.acquire(source_id, lock_ttl)
            if not _lock_acquired:
                return None, "Already fetching"

            if not source.enabled and not manual_trigger:
                fetch_lock.release(source_id)
                return None, "Source is disabled"

            if not PODCAST_SOURCES_ENABLED:
                source_type = source.type.value if hasattr(source.type, "value") else str(source.type)
                if source_type == "podcast":
                    fetch_lock.release(source_id)
                    return None, "Podcast sources are disabled"

            # 域名限速检查
            domain = normalize_host(source.url)
            if not domain_limiter.acquire(domain):
                logger.info(f"Rate-limited domain for source: {source_id} ({domain})")
                fetch_lock.release(source_id)
                return None, "Domain rate limited"

            return source, None

        source, skip_reason = await asyncio.to_thread(_query_and_lock)

        if skip_reason:
            if skip_reason == "Source not found":
                logger.error(f"Source not found: {source_id}")
                return {"status": "error", "message": skip_reason}
            logger.info(f"Skip fetch for source {source_id}: {skip_reason}")
            return {"status": "skipped", "message": skip_reason}

        lock_acquired = True

        # --- 阶段 2：在主事件循环中直接 await pipeline（共享连接池/信号量） ---
        result = await run_fetch_pipeline(db, source, manual_trigger)

        # 收集新内容 ID 用于 AI 后处理
        new_ids = []
        if result.get("saved", 0) > 0:
            new_ids = result.get("new_content_ids", [])

        result = {**result, "new_content_ids": new_ids}

        # Dispatch non-blocking ingest-finalization for new content.
        if new_ids:
            from app.tasks.task_queue import task_queue
            for cid in new_ids:
                await task_queue.enqueue_ingest_finish(str(cid), job_id=job_id)

        return result

    except Exception as exc:
        logger.error(f"Fetch failed for {source_id}: {exc}")
        await asyncio.to_thread(persist_fetch_task_exception, source_id, exc)

    finally:
        # 确保锁释放和 DB 关闭在线程中执行（避免同步 I/O 阻塞事件循环）
        def _cleanup():
            if lock_acquired:
                fetch_lock.release(source_id)
            if db is not None:
                db.close()
        await asyncio.to_thread(_cleanup)


async def fetch_all_sources(manual_trigger: bool = False):
    """Fetch all enabled sources in parallel."""
    logger.info("Fetching all enabled sources")

    from app.database import SessionLocal
    from app.models import Source

    def _query_sources():
        db = SessionLocal()
        try:
            query = db.query(Source).filter(Source.enabled.is_(True))
            if not PODCAST_SOURCES_ENABLED:
                query = query.filter(Source.type != SourceType.PODCAST)
            sources = query.all()
            return [str(s.id) for s in sources]
        finally:
            db.close()

    source_ids = await asyncio.to_thread(_query_sources)

    from app.tasks.task_queue import task_queue
    scheduled = 0
    for sid in source_ids:
        if fetch_lock.is_locked(sid):
            continue
        await task_queue.enqueue_fetch(sid, manual_trigger=manual_trigger)
        scheduled += 1

    logger.info(f"Dispatched {scheduled}/{len(source_ids)} fetch tasks")
    return {"status": "success", "total": len(source_ids), "scheduled": scheduled}


# When multiple sources come due in the same scheduler tick we stagger their
# enqueue by up to this many seconds so the target hosts don't see a wall of
# synchronized requests. Kept tight enough that fetches still happen within
# the same minute; long enough to visibly de-correlate starts.
_STARTUP_JITTER_SECONDS = 30.0


async def check_and_fetch_due_sources():
    """Scheduled job: check for sources due for fetching and dispatch.

    The due check itself is owned by
    :func:`app.domains.sources.scheduling.list_due_source_ids`; this
    function only handles the async dispatch concern (semaphore, lock,
    jittered enqueue).
    """
    logger.info("Checking for sources due for fetching")

    from app.database import SessionLocal

    def _query_due():
        db = SessionLocal()
        try:
            return list_due_source_ids(db)
        finally:
            db.close()

    due_ids = await asyncio.to_thread(_query_due)

    from app.tasks.task_queue import task_queue

    async def _delayed_enqueue(sid: str, delay_s: float) -> None:
        try:
            if delay_s > 0:
                await asyncio.sleep(delay_s)
            if fetch_lock.is_locked(sid):
                return
            await task_queue.enqueue_fetch(sid)
        except Exception:  # noqa: BLE001 - best-effort; log and move on
            logger.exception("Delayed enqueue failed for source %s", sid)

    # Skip the jitter when a single source is due — no correlation risk
    # and a user watching a lone feed shouldn't wait extra seconds for no
    # reason. Above that, spread starts across [0, _STARTUP_JITTER_SECONDS).
    scheduled = 0
    use_jitter = len(due_ids) > 1
    for sid in due_ids:
        if fetch_lock.is_locked(sid):
            continue
        delay = random.uniform(0.0, _STARTUP_JITTER_SECONDS) if use_jitter else 0.0
        asyncio.create_task(_delayed_enqueue(sid, delay))
        scheduled += 1

    logger.info(
        "Scheduled %s/%s due sources (startup_jitter=%ss%s)",
        scheduled,
        len(due_ids),
        _STARTUP_JITTER_SECONDS if use_jitter else 0,
        ", jittered" if use_jitter else "",
    )
