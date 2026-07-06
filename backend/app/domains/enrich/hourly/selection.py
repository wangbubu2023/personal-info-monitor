"""Candidate-selection step for hourly digest generation.

Given the pre-ranked entries for the last 60 minutes, ask the LLM to pick
the most important ``N`` content IDs. Fall back to the local ranking
service when the LLM output is malformed or empty.
"""

from __future__ import annotations

import json
import re
from typing import List

from app.ai.provider import ModelProviderClient
from app.domains.enrich.hourly.text_utils import (
    clean_digest_text,
    preferred_item_title,
    strip_ranking_internal,
)
from app.domains.score.ranking import RankingService

_MAX_CATALOG_ENTRIES = 80


def build_selection_catalog(entries: List[dict]) -> str:
    lines: List[str] = []
    for e in entries[:_MAX_CATALOG_ENTRIES]:
        cid = (e.get("content_id") or "").strip()
        if not cid:
            continue
        meta = e.get("metadata") if isinstance(e.get("metadata"), dict) else {}
        title = preferred_item_title(e)
        sn = (e.get("source_name") or "").strip()
        summ = clean_digest_text((e.get("translated_summary") or e.get("summary") or "").strip())
        if len(summ) > 280:
            summ = f"{summ[:277]}..."
        final_score = e.get("final_score", meta.get("final_score"))
        article_score = e.get("article_score", meta.get("article_score", final_score))
        lane = e.get("lane", meta.get("lane"))
        source_stars = e.get("source_stars", meta.get("source_stars"))
        fulltext_status = e.get("fulltext_status", meta.get("fulltext_status"))
        quality_parts = []
        if article_score is not None:
            quality_parts.append(f"评分={article_score}")
        if lane:
            quality_parts.append(f"赛道={lane}")
        if source_stars is not None:
            quality_parts.append(f"信源={source_stars}星")
        if fulltext_status:
            quality_parts.append(f"正文={fulltext_status}")
        quality_line = f"  质量={'；'.join(quality_parts)}\n" if quality_parts else ""
        lines.append(f"content_id={cid}\n  来源={sn}\n  标题={title}\n  摘要={summ}\n")
        if quality_line:
            lines[-1] = lines[-1] + quality_line
    return "\n".join(lines).strip()


def parse_selection_ids(raw: str, valid_ids: set, max_n: int) -> List[str]:
    """Parse the LLM's JSON reply into a de-duplicated, capped list of known IDs.

    Tolerates markdown fences and leading/trailing chatter, but only
    accepts values that map back to our candidate set. Unknown or
    malformed output collapses to an empty list so callers can fall back
    to local ranking.
    """
    s = (raw or "").strip()
    if not s:
        return []
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.I)
        s = re.sub(r"\s*```\s*$", "", s)
    data = None
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", s)
        if m:
            try:
                data = json.loads(m.group(0))
            except json.JSONDecodeError:
                data = None
    if data is None:
        return []
    ids = []
    if isinstance(data, dict):
        ids = data.get("ids") or data.get("selected") or data.get("content_ids") or []
    elif isinstance(data, list):
        ids = data
    if not isinstance(ids, list):
        return []
    out: List[str] = []
    for x in ids:
        cid = str(x).strip()
        if cid in valid_ids and cid not in out:
            out.append(cid)
        if len(out) >= max_n:
            break
    return out


def fallback_pick_ids_from_ranking(entries: List[dict], max_pick: int) -> List[str]:
    ranking_service = RankingService()
    clusters = ranking_service.cluster_and_rank(entries)[:max_pick]
    out: List[str] = []
    for c in clusters:
        items = c.get("items") or []
        if not items:
            continue
        it = strip_ranking_internal(items[0])
        cid = (it.get("content_id") or "").strip()
        if cid and cid not in out:
            out.append(cid)
    return out


def ordered_entries_by_ids(entries: List[dict], ids: List[str]) -> List[dict]:
    by_id = {
        str(e.get("content_id") or "").strip(): e
        for e in entries
        if (e.get("content_id") or "").strip()
    }
    return [by_id[i] for i in ids if i in by_id]


async def llm_select_content_ids(
    model_client: ModelProviderClient,
    runtime,
    *,
    catalog: str,
    task_prompt: str,
    max_pick: int,
) -> str:
    prompt = (
        f"你正在生成「每小时简报」，当前是选稿步骤。下列任务说明在后续写综述时同样有效，请一并遵守。\n\n"
        f"{task_prompt}\n\n"
        f"---\n"
        f"输出格式要求：下面是本次简报窗口内新增入库、得分排名前 20 的候选（每条以 content_id= 开头，id 必须原样复制到输出中）。\n"
        f"请最多选出 {max_pick} 条，按重要性降序。\n"
        f"只输出一个 JSON 对象，形如 {{\"ids\":[\"uuid\",...]}}。不要 markdown 围栏，不要解释。\n\n"
        f"{catalog}"
    )
    return await model_client.generate_text(
        runtime,
        prompt=prompt,
        system_prompt="只输出合法 JSON，且必须包含键 ids（字符串数组）。不要输出其它文字。",
        temperature=0.05,
        max_tokens=800,
        timeout_seconds=75.0,
    )
