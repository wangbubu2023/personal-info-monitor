"""Tasks for fetching content from sources — high-concurrency async engine."""

import asyncio
import random
from datetime import timedelta
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
from app.domains.fetch.coordinator import run_fetch_pipeline
from app.domains.sources.status import persist_fetch_task_exception
from app.utils.logger import get_logger, bind_job_id, restore_job_id
from app.utils.url import normalize_host
from app.utils.datetime import utcnow_naive

logger = get_logger(__name__)
settings = get_settings()


async def fetch_source(
    source_id: str,
    manual_trigger: bool = False,
    fetch_job_id: str | None = None,
):
    """Fetch content from a single source. Runs pipeline in a thread."""
    job_id = fetch_job_id or uuid4().hex
    token = bind_job_id(job_id)
    try:
        logger.info(
            "Starting fetch for source: %s (manual=%s)", source_id, manual_trigger,
            extra={"phase": "fetch", "source_id": source_id},
        )
        sem = get_fetch_semaphore()
        async with sem:
            tracker_started = False
            try:
                await task_tracker.start_fetch()
                tracker_started = True
                return await _do_fetch(source_id, manual_trigger, job_id=job_id)
            finally:
                if tracker_started:
                    await task_tracker.end_fetch()
    finally:
        restore_job_id(token)


async def _do_fetch(source_id: str, manual_trigger: bool, job_id: str | None = None):
    """执行单源抓取：短生命周期准入检查 + 主循环 async pipeline。"""
    from app.database import SessionLocal
    from app.domains.fetch.failures import FetchFailureCode, FetchFailureError, make_failure
    from sqlalchemy.orm import joinedload

    from app.models import Source

    lock_acquired = False
    db = None

    try:
        # --- 阶段 1：在线程中执行短生命周期准入检查。不要把 SQLAlchemy
        # Session 或 ORM row 跨线程传给 pipeline；pipeline 会在自己的线程
        # 中重新打开 Session 并重新查询 Source。
        def _query_and_lock():
            gate_db = SessionLocal()
            try:
                source = gate_db.query(Source).filter(Source.id == source_id).first()
                if not source:
                    return "Source not found"

                lock_ttl = max(300, int((source.fetch_interval or 60) * 60))
                _lock_acquired = fetch_lock.acquire(source_id, lock_ttl)
                if not _lock_acquired:
                    return "Already fetching"

                if not source.enabled and not manual_trigger:
                    fetch_lock.release(source_id)
                    return "Source is disabled"

                if not PODCAST_SOURCES_ENABLED:
                    source_type = source.type.value if hasattr(source.type, "value") else str(source.type)
                    if source_type == "podcast":
                        fetch_lock.release(source_id)
                        return "Podcast sources are disabled"

                # 域名限速检查
                domain = normalize_host(source.url)
                if not domain_limiter.acquire(domain):
                    logger.info(f"Rate-limited domain for source: {source_id} ({domain})")
                    fetch_lock.release(source_id)
                    return "Domain rate limited"

                return None
            finally:
                gate_db.close()

        skip_reason = await asyncio.to_thread(_query_and_lock)

        if skip_reason:
            failure_codes = {
                "Source not found": FetchFailureCode.SOURCE_NOT_FOUND,
                "Already fetching": FetchFailureCode.FETCH_ALREADY_RUNNING,
                "Source is disabled": FetchFailureCode.SOURCE_DISABLED,
                "Podcast sources are disabled": FetchFailureCode.SOURCE_TYPE_DISABLED,
                "Domain rate limited": FetchFailureCode.DOMAIN_RATE_LIMITED,
            }
            failure = make_failure(failure_codes.get(skip_reason, FetchFailureCode.UNKNOWN))
            logger.warning("Fetch gate rejected source %s: %s", source_id, failure.code.value)
            raise FetchFailureError(failure)

        lock_acquired = True

        # --- 阶段 2：在线程中创建 Session 并完整装载 pipeline 所需的
        # Source/Auth ORM 状态。同步连接池 checkout 与 SELECT 绝不能发生在
        # uvicorn event loop 上；高并发时一次 checkout 等待即可冻结 HTTP。
        def _open_pipeline_session():
            pipeline_db = SessionLocal()
            try:
                pipeline_source = (
                    pipeline_db.query(Source)
                    .options(joinedload(Source.auth_config))
                    .filter(Source.id == source_id)
                    .first()
                )
                return pipeline_db, pipeline_source
            except Exception:
                pipeline_db.close()
                raise

        db, source = await asyncio.to_thread(_open_pipeline_session)
        if not source:
            raise FetchFailureError(make_failure(FetchFailureCode.SOURCE_NOT_FOUND))

        # The coordinator is cooperative async code. Every synchronous ORM or
        # CPU-heavy stage inside it is explicitly sent to a worker thread.
        result = await run_fetch_pipeline(db, source, manual_trigger)

        candidates = list(result.get("postprocess_candidates") or [])
        new_ids = [str(item.get("content_id")) for item in candidates if item.get("content_id")]
        result = {**result, "new_content_ids": new_ids}

        # The content fingerprint + pipeline version is the execution
        # idempotency boundary. A fetch trace UUID must never force the same
        # expensive content through the pipeline twice.
        if candidates:
            from app.tasks.task_queue import task_queue

            for candidate in candidates:
                content_id = str(candidate["content_id"])
                candidate_job_id = (
                    f"finish:{candidate['pipeline_version']}:{candidate['content_fingerprint']}"
                )
                await task_queue.enqueue_ingest_finish(content_id, job_id=candidate_job_id)

        return result

    except Exception as exc:
        logger.error(f"Fetch failed for {source_id}: {exc}")
        await asyncio.to_thread(persist_fetch_task_exception, source_id, exc)
        raise

    finally:
        if lock_acquired:
            await asyncio.to_thread(fetch_lock.release, source_id)
        if db is not None:
            await asyncio.to_thread(db.close)


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
    persisted = enqueued = duplicates = rejected = 0
    job_ids: list[str] = []
    for sid in source_ids:
        dispatch = await task_queue.enqueue_fetch(
            sid,
            manual_trigger=manual_trigger,
            fetch_kind="bulk_manual" if manual_trigger else "scheduled",
        )
        persisted += int(dispatch.persisted and not dispatch.duplicate)
        enqueued += int(dispatch.enqueued)
        duplicates += int(dispatch.duplicate)
        rejected += int(dispatch.rejected)
        if dispatch.job_id:
            job_ids.append(dispatch.job_id)

    logger.info("Persisted %s/%s fetch jobs (enqueued=%s duplicate=%s rejected=%s)", persisted, len(source_ids), enqueued, duplicates, rejected)
    return {
        "status": "partial" if rejected or enqueued < persisted else "success",
        "requested_count": len(source_ids),
        "persisted_count": persisted,
        "accepted_count": persisted,
        "enqueued_count": enqueued,
        "duplicate_count": duplicates,
        "rejected_count": rejected,
        "failed_count": rejected,
        "job_ids": job_ids,
    }


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

    # Skip the jitter when a single source is due — no correlation risk
    # and a user watching a lone feed shouldn't wait extra seconds for no
    # reason. Above that, spread starts across [0, _STARTUP_JITTER_SECONDS).
    persisted = enqueued = duplicates = rejected = 0
    use_jitter = len(due_ids) > 1
    due_window = utcnow_naive()
    for sid in due_ids:
        delay = random.uniform(0.0, _STARTUP_JITTER_SECONDS) if use_jitter else 0.0
        dispatch = await task_queue.enqueue_fetch(
            sid,
            fetch_kind="scheduled",
            due_window=due_window,
            not_before=due_window + timedelta(seconds=delay),
        )
        persisted += int(dispatch.persisted and not dispatch.duplicate)
        enqueued += int(dispatch.enqueued)
        duplicates += int(dispatch.duplicate)
        rejected += int(dispatch.rejected)

    logger.info(
        "Persisted %s/%s due sources (enqueued=%s duplicate=%s rejected=%s startup_jitter=%ss%s)",
        persisted,
        len(due_ids),
        enqueued,
        duplicates,
        rejected,
        _STARTUP_JITTER_SECONDS if use_jitter else 0,
        ", jittered" if use_jitter else "",
    )
    return {
        "requested_count": len(due_ids),
        "persisted_count": persisted,
        "accepted_count": persisted,
        "enqueued_count": enqueued,
        "duplicate_count": duplicates,
        "rejected_count": rejected,
        "failed_count": rejected,
    }
