"""Orchestration entry-point for the hourly digest generator.

Responsibilities kept small on purpose:

1. Load the previous hour's context via
   :func:`app.domains.enrich.hourly.repository.build_digest_generation_context`.
2. Negotiate an AI runtime from system settings (fallback to a
   rule-based digest when none is configured).
3. Run the AI selection → synthesis path; on any failure drop back
   through per-cluster generation and finally the rule-based fallback.
4. Persist the final body via
   :func:`app.domains.enrich.hourly.repository.store_digest`.

All parsing / prompt / DB helpers live in ``app.domains.enrich.hourly``.
Module-level re-exports at the bottom keep the legacy
``hourly_digest_tasks._foo`` surface intact for existing callers and
tests.
"""

from __future__ import annotations

import asyncio

from app.ai.provider import ModelProviderClient, get_runtime_from_system_settings
from app.domains.enrich.hourly.repository import (
    build_hourly_digest_event_items,
    build_digest_generation_context,
    clear_hourly_digests,
    store_digest,
)
from app.domains.enrich.hourly.selection import (
    build_selection_catalog,
    fallback_pick_ids_from_ranking,
    llm_select_content_ids,
    ordered_entries_by_ids,
    parse_selection_ids,
)
from app.domains.enrich.hourly.synthesis import (
    build_synthesis_materials,
    generate_digest_items_with_ai,
    build_digest_from_items,
    build_fallback_digest,
    llm_synthesize_hourly_digest,
    localize_fallback_clusters,
)
from app.domains.enrich.hourly.text_utils import (
    SYSTEM_TZ,
    get_digest_limits,
    hourly_digest_user_settings,
    is_valid_digest_format,
    strip_llm_reasoning,
)
from app.domains.score.ranking import RankingService
from app.platform.config.system_settings import effective_hourly_digest_prompt
from app.utils.llm_guardrail import is_rejected_selection
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def generate_previous_hour_digest() -> None:
    """Generate the digest for the previous hour.

    See the module docstring for the full decision tree; the short
    version: try LLM select + synthesize → if invalid, per-cluster
    LLM generation → if still invalid, rule-based fallback.
    """

    def _load_context():
        from app.database import SessionLocal

        db = SessionLocal()
        try:
            return db, build_digest_generation_context(db)
        except Exception:
            db.close()
            raise

    db, ctx = await asyncio.to_thread(_load_context)
    if ctx is None:
        db.close()
        return

    runtime = await get_runtime_from_system_settings(
        setting_key="ai_model",
        default_provider="ollama",
        default_model="",
        default_api_base="http://localhost:11434",
        default_temperature=0.2,
        default_max_tokens=2400,
    )

    model_client = ModelProviderClient()
    limits = get_digest_limits()
    max_pick = min(8, limits["max_candidates"])
    try:
        entries = ctx["entries"]
        event_items = build_hourly_digest_event_items(entries)

        def _ranked_clusters(n: int):
            # Keep content the selection stage already rejected/deferred out of
            # AI fallbacks: it must not be resurrected (and risk being rewritten
            # into something unrelated) just because the primary path failed.
            eligible = [e for e in entries if not is_rejected_selection(e.get("selection_status"))]
            return RankingService().cluster_and_rank(eligible)[:n]

        # --- Path 0: no AI runtime configured → emit a clean rule-based digest.
        if not runtime:
            clusters = _ranked_clusters(max_pick)
            await localize_fallback_clusters(clusters, candidate_limit=len(clusters))
            fallback_body = build_fallback_digest(
                ctx["title"],
                clusters,
                candidate_limit=len(clusters),
                reason="当前未配置可用 AI 模型或 Ollama 未安装指定模型，已生成简版简报。请到「设置 → AI 模型」检查 provider/model/API Key 配置。",
            )

            def _save_fallback_without_runtime():
                store_digest(
                    db,
                    ctx["digest"],
                    ctx["title"],
                    fallback_body,
                    content_count=len(ctx["rows"]),
                    sources=ctx["source_names"],
                    items_json=event_items,
                )

            await asyncio.to_thread(_save_fallback_without_runtime)
            logger.info("Stored fallback hourly digest because no AI runtime is available")
            return

        # --- Path 1: LLM picks IDs then writes the full synthesis in one shot.
        hd = hourly_digest_user_settings()
        task_prompt = effective_hourly_digest_prompt(hd)
        body = ""
        degrade_reason: str | None = None

        try:
            catalog = build_selection_catalog(entries)
            valid_ids = {
                str(e.get("content_id") or "").strip()
                for e in entries
                if (e.get("content_id") or "").strip()
            }
            raw_pick = await llm_select_content_ids(
                model_client,
                runtime,
                catalog=catalog,
                task_prompt=task_prompt,
                max_pick=max_pick,
            )
            picked = parse_selection_ids(raw_pick, valid_ids, max_pick)
            if not picked:
                picked = fallback_pick_ids_from_ranking(entries, max_pick)
            selected = ordered_entries_by_ids(entries, picked)
            if not selected:
                selected = entries[:max_pick]

            materials = build_synthesis_materials(selected)
            body = await llm_synthesize_hourly_digest(
                model_client,
                runtime,
                title=ctx["title"],
                materials=materials,
                task_prompt=task_prompt,
            )
            body = strip_llm_reasoning(body)
        except Exception as e:  # noqa: BLE001 - model/network can raise anything; fall through to path 2
            logger.warning("Hourly digest synthesis path failed (%s): %s", runtime.provider, e)
            degrade_reason = f"模型调用失败（{runtime.provider}）：{e}"
            body = ""

        # --- Path 2: per-cluster AI fallback when the one-shot output doesn't validate.
        if not is_valid_digest_format(body):
            clusters = _ranked_clusters(max_pick)
            try:
                await localize_fallback_clusters(clusters, candidate_limit=len(clusters))
                generated_items = await generate_digest_items_with_ai(
                    model_client,
                    runtime,
                    clusters,
                    candidate_limit=min(6, len(clusters)),
                )
                body = (
                    build_digest_from_items(ctx["title"], generated_items)
                    if generated_items
                    else ""
                )
                body = strip_llm_reasoning(body)
                if not body and degrade_reason is None:
                    degrade_reason = "按簇逐条生成也没有产出有效内容。"
            except Exception as e2:  # noqa: BLE001 - both AI paths failed; fall through to path 3
                logger.warning(
                    "Hourly digest per-cluster fallback failed (%s): %s", runtime.provider, e2
                )
                if degrade_reason is None:
                    degrade_reason = f"按簇生成也失败（{runtime.provider}）：{e2}"
                body = ""

        # --- Path 3: pure rule-based fallback when both AI paths fail format validation.
        if not is_valid_digest_format(body):
            logger.warning("Digest output invalid, storing ranked fallback digest")
            clusters = _ranked_clusters(max_pick)
            await localize_fallback_clusters(clusters, candidate_limit=len(clusters))
            reason = degrade_reason or "综述生成未通过校验或模型输出异常，已回退为分类简版（含本地阅读链接）。"
            body = build_fallback_digest(
                ctx["title"],
                clusters,
                candidate_limit=min(6, len(clusters)),
                reason=reason,
            )

        def _save():
            store_digest(
                db,
                ctx["digest"],
                ctx["title"],
                body,
                content_count=len(ctx["rows"]),
                sources=ctx["source_names"],
                items_json=event_items,
            )

        await asyncio.to_thread(_save)
        logger.info("Generated hourly digest for %s", ctx["title"])
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Backwards-compatible re-exports.
#
# The original monolithic module exposed ~30 private helpers that downstream
# tests access as ``hourly_digest_tasks._foo``. Keep those symbols pointing at
# the new implementations so pre-existing test files continue to work without
# having to rewrite them. New code should import from the sub-modules directly.
# ---------------------------------------------------------------------------

from app.domains.enrich.hourly import repository as _repository  # noqa: E402
from app.domains.enrich.hourly import selection as _selection  # noqa: E402
from app.domains.enrich.hourly import synthesis as _synthesis  # noqa: E402
from app.domains.enrich.hourly import text_utils as _text_utils  # noqa: E402
from app.platform.config.system_settings import get_system_settings_sync  # noqa: E402,F401 - legacy re-export

_local_to_utc_naive = _text_utils.local_to_utc_naive
_format_digest_title = _text_utils.format_digest_title
_coerce_limit_int = _text_utils.coerce_limit_int
_get_digest_limits = _text_utils.get_digest_limits
_hourly_digest_user_settings = _text_utils.hourly_digest_user_settings
_strip_ranking_internal = _text_utils.strip_ranking_internal
_clean_digest_text = _text_utils.clean_digest_text
_preferred_item_title = _text_utils.preferred_item_title
_preferred_item_summary = _text_utils.preferred_item_summary
_normalize_digest_category = _text_utils.normalize_digest_category
_classify_digest_category = _text_utils.classify_digest_category
_is_valid_digest_format = _text_utils.is_valid_digest_format

_build_selection_catalog = _selection.build_selection_catalog
_parse_selection_ids = _selection.parse_selection_ids
_fallback_pick_ids_from_ranking = _selection.fallback_pick_ids_from_ranking
_ordered_entries_by_ids = _selection.ordered_entries_by_ids
_llm_select_content_ids = _selection.llm_select_content_ids

_build_synthesis_materials = _synthesis.build_synthesis_materials
_llm_synthesize_hourly_digest = _synthesis.llm_synthesize_hourly_digest
_build_prompt = _synthesis.build_cluster_prompt_v1
_build_cluster_item_prompt = _synthesis.build_cluster_item_prompt
_parse_generated_digest_item = _synthesis.parse_generated_digest_item
_build_digest_from_items = _synthesis.build_digest_from_items
_build_fallback_digest = _synthesis.build_fallback_digest
_localize_fallback_clusters = _synthesis.localize_fallback_clusters
_generate_digest_items_with_ai = _synthesis.generate_digest_items_with_ai

_build_digest_text_seed = _repository.build_digest_text_seed
_build_entries = _repository.build_entries
_build_hourly_digest_event_items = _repository.build_hourly_digest_event_items
_compute_digest_window = _repository.compute_digest_window
_load_digest_rows = _repository.load_digest_rows
_get_or_create_hourly_digest = _repository.get_or_create_hourly_digest
_store_digest = _repository.store_digest
_store_empty_digest = _repository.store_empty_digest
_build_digest_generation_context = _repository.build_digest_generation_context
