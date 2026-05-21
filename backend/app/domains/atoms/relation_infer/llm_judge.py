"""LLM judge for corroboration vs contradiction between atom pairs."""

from __future__ import annotations

import json
import re
from typing import Any

from app.ai.provider import ModelProviderClient, get_runtime_from_system_settings
from app.domains.atoms.types import AtomRecord, RelationCreate
from app.domains.atoms.vocab import RelationDirection, RelationType
from app.utils.logger import get_logger

logger = get_logger(__name__)

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)
_THINKING_RE = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)


def _strip_llm_wrapper(text: str) -> str:
    body = _THINKING_RE.sub("", text or "").strip()
    match = _JSON_FENCE_RE.search(body)
    if match:
        return match.group(1).strip()
    return body


def _atom_summary(atom: AtomRecord) -> dict[str, Any]:
    return {
        "atom_id": atom.atom_id,
        "atom_type": atom.atom_type.value,
        "domain": atom.domain.value,
        "source_sentence": atom.source_sentence,
        "atom_source": atom.atom_source,
        "payload": atom.payload,
    }


def build_relation_prompt(atom_a: AtomRecord, atom_b: AtomRecord) -> tuple[str, str]:
    system = (
        "你是新闻事实关系判定助手。比较两条跨文章原子，判断是否存在印证或矛盾关系。\n"
        "只输出 JSON：{\"relation_type\":\"印证\"|\"矛盾\"|null,\"direction\":\"双向\"|\"A→B\"|\"B→A\","
        "\"fact_confidence\":0.0-1.0,\"reason\":\"...\"}\n"
        "规则：\n"
        "1. 无明确印证或矛盾时 relation_type 为 null。\n"
        "2. 印证 → direction 必须为「双向」。\n"
        "3. 矛盾 → direction 按语义（A→B 表示 atom_a 与 atom_b 冲突的方向）。\n"
        "4. 不要输出 markdown 围栏。"
    )
    user = json.dumps(
        {"atom_a": _atom_summary(atom_a), "atom_b": _atom_summary(atom_b)},
        ensure_ascii=False,
        indent=2,
    )
    return system, user


def parse_relation_judgment(
    text: str,
    *,
    atom_a: str,
    atom_b: str,
) -> RelationCreate | None:
    raw = _strip_llm_wrapper(text)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.debug("relation judge JSON parse failed: %s", raw[:200])
        return None

    rel_type = data.get("relation_type")
    if rel_type is None or rel_type == "null":
        return None

    try:
        relation_type = RelationType(rel_type)
    except ValueError:
        return None

    if relation_type not in (RelationType.CORROBORATION, RelationType.CONTRADICTION):
        return None

    direction_raw = data.get("direction") or RelationDirection.BIDIRECTIONAL.value
    if relation_type == RelationType.CORROBORATION:
        direction = RelationDirection.BIDIRECTIONAL
    else:
        try:
            direction = RelationDirection(direction_raw)
        except ValueError:
            direction = RelationDirection.A_TO_B

    confidence = data.get("fact_confidence", 0.7)
    try:
        fact_confidence = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        fact_confidence = 0.7

    return RelationCreate(
        atom_a=atom_a,
        atom_b=atom_b,
        relation_type=relation_type,
        direction=direction,
        fact_confidence=fact_confidence,
        verified=False,
    )


async def judge_relation_pair(atom_a: AtomRecord, atom_b: AtomRecord) -> RelationCreate | None:
    """Call LLM to classify relation between two atoms. Returns None when inconclusive."""
    runtime = await get_runtime_from_system_settings(
        setting_key="ai_model",
        default_provider="ollama",
        default_model="",
        default_api_base="http://localhost:11434",
        default_temperature=0.1,
        default_max_tokens=1500,
    )
    if runtime is None:
        return None

    system, user = build_relation_prompt(atom_a, atom_b)
    client = ModelProviderClient()
    try:
        raw = await client.generate_text(
            runtime,
            prompt=user,
            system_prompt=system,
            temperature=0.1,
            max_tokens=1500,
            timeout_seconds=90.0,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("relation LLM judge failed: %s", exc)
        return None

    return parse_relation_judgment(raw, atom_a=atom_a.atom_id, atom_b=atom_b.atom_id)


__all__ = [
    "build_relation_prompt",
    "judge_relation_pair",
    "parse_relation_judgment",
]
