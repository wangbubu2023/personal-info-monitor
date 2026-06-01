"""LLM prompt + parser for atom reconcile operations."""

from __future__ import annotations

import json
import re
from typing import Any

from app.domains.atoms.atom_reconcile.types import AtomReconcileOp, ReconcileOpType
from app.domains.atoms.types import AtomRecord
from app.utils.logger import get_logger

logger = get_logger(__name__)

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)
_THINKING_RE = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)


def _strip_wrapper(text: str) -> str:
    body = _THINKING_RE.sub("", text or "").strip()
    match = _JSON_FENCE_RE.search(body)
    return match.group(1).strip() if match else body


def _atom_brief(atom: AtomRecord) -> dict[str, Any]:
    return {
        "atom_id": atom.atom_id,
        "atom_type": atom.atom_type.value,
        "canonical_text": atom.canonical_text or atom.source_sentence,
        "atom_source": atom.atom_source,
    }


def build_reconcile_prompt(
    new_atom: AtomRecord,
    candidates: list[AtomRecord],
) -> tuple[str, str]:
    system = (
        "你是新闻原子库维护系统。判断新 atom 与候选旧 atom 的关系，输出单个操作。\n"
        "只允许输出以下 op 之一：ADD / MERGE / SUPERSEDE / CONTRADICT / IGNORE。\n"
        "- ADD：新 atom 与旧库无关或为独立新事实，保持 active。\n"
        "- MERGE：新 atom 与某旧 atom 是同一事实的碎片，合并且信息不丢失。\n"
        "- SUPERSEDE：同一事实维度新旧状态不能同时成立，新 atom 覆盖旧 atom。\n"
        "- CONTRADICT：不同来源给出互相冲突说法，二者都不删除。\n"
        "- IGNORE：新 atom 是 boilerplate/标题/代码/字段失真/重复低价值内容。\n"
        "输出 JSON：{\"op\":\"...\",\"atom_id\":\"目标旧atom_id或null\","
        "\"candidate_atom_ids\":[...],\"reason\":\"...\",\"confidence\":0.0-1.0}\n"
        "不要输出 markdown 围栏。"
    )
    user = json.dumps(
        {
            "new_atom": _atom_brief(new_atom),
            "candidates": [_atom_brief(c) for c in candidates],
        },
        ensure_ascii=False,
        indent=2,
    )
    return system, user


def parse_reconcile_op(text: str) -> AtomReconcileOp | None:
    raw = _strip_wrapper(text)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            logger.debug("reconcile op not JSON: %s", raw[:200])
            return None
        try:
            data = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None

    op_raw = str(data.get("op") or "").strip().upper()
    if op_raw not in {t.value for t in ReconcileOpType}:
        return None
    try:
        return AtomReconcileOp(
            op=ReconcileOpType(op_raw),
            atom_id=(str(data["atom_id"]) if data.get("atom_id") else None),
            candidate_atom_ids=[str(x) for x in (data.get("candidate_atom_ids") or []) if x],
            reason=str(data.get("reason") or ""),
            confidence=float(data.get("confidence", 0.7)),
        )
    except (TypeError, ValueError):
        return None


__all__ = ["build_reconcile_prompt", "parse_reconcile_op"]
