"""LLM prompt + response parsing for atom extraction."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from app.domains.atoms.credibility import resolve_credibility
from app.domains.atoms.extractor.normalize import normalize_extraction_domain, normalize_extraction_payload
from app.domains.atoms.extractor.validate import resolve_source_sentence
from app.domains.atoms.types import AtomCreate, payload_from_dict
from app.domains.atoms.vocab import AtomType, Domain
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


def _enum_doc() -> str:
    return (
        "atom_type: 信息|观点|数据\n"
        f"domain: {'|'.join(d.value for d in Domain)}\n"
        "信息 payload 字段: when, where, who[{name,type}], why, what_type, what, how, result, entities[], validity\n"
        "观点 payload 字段: who[{name,type}], role, say_what, is_quote, context, sentiment, intensity\n"
        "数据 payload 字段: source_org, source_type, metric, value, unit, caliber, period, period_type, is_relative, base_value, base_period, validity\n"
    )


def build_extraction_prompt(
    *,
    sentences: list[str],
    article_title: str,
    carrier_source: str,
) -> tuple[str, str]:
    numbered = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(sentences))
    system = (
        "你是新闻原子库的核心事实抽取助手。从给定句子中只提取高价值核心事实，严格输出 JSON。\n"
        "规则：\n"
        "1. 只抽对新闻理解、后续追踪、跨文档关联有价值的核心事实。\n"
        "2. 不要抽标题、栏目名、代码片段、列表标签、广告声明、版权声明、作者介绍。\n"
        "3. 每个输入 batch 最多输出 5 条 atom；宁缺毋滥。\n"
        "4. 同一句 source_sentence 只能输出 1 条 atom_type，选择最能表达信息价值的类型。\n"
        "5. source_sentence 必须从原文句子逐字复制，禁止改写。\n"
        "6. atom_source 是这条事实的陈述来源（如「据路透报道」→ 路透；否则用发文媒体）。\n"
        "7. payload 内放类型专属字段；who 统一为 [{name,type}] 列表。\n"
        "8. 只输出 JSON 对象 {\"atoms\":[...]}，不要 markdown 围栏。\n"
        "fact_confidence 校准：\n"
        "- 0.9-1.0：原句有明确主体、动作/指标、时间/范围，且字段完整。\n"
        "- 0.7-0.8：一般事实陈述，字段基本完整。\n"
        "- 0.5-0.6：弱事实、语义不完整、来源不明、推断性强。\n"
        "- 低于 0.7 的信息/数据不要输出；低于 0.6 的观点不要输出。\n"
        f"{_enum_doc()}"
    )
    user = (
        f"文章标题：{article_title}\n"
        f"入库媒体（载体）：{carrier_source}\n\n"
        f"待分析句子：\n{numbered}\n\n"
        "输出 JSON：{\"atoms\":[{\"atom_type\":\"...\",\"source_sentence\":\"...\","
        "\"atom_source\":\"...\",\"domain\":\"...\",\"fact_confidence\":0.8,\"payload\":{...}}]}"
    )
    return system, user


def parse_llm_atoms(
    raw_text: str,
    *,
    content_id: str,
    source_url: str,
    full_text: str,
) -> list[AtomCreate]:
    cleaned = _strip_llm_wrapper(raw_text)
    if not cleaned:
        return []

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to salvage first JSON object
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            logger.debug("atom LLM output is not JSON: %s", cleaned[:200])
            return []
        try:
            data = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            logger.debug("atom LLM JSON salvage failed")
            return []

    items = data.get("atoms") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []

    results: list[AtomCreate] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            atom = _item_to_atom_create(
                item,
                content_id=content_id,
                source_url=source_url,
                full_text=full_text,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("skip invalid atom item: %s", exc)
            continue
        if atom is not None:
            results.append(atom)
    return results


def _item_to_atom_create(
    item: dict[str, Any],
    *,
    content_id: str,
    source_url: str,
    full_text: str,
) -> AtomCreate | None:
    atom_type_raw = str(item.get("atom_type") or "").strip()
    if atom_type_raw not in {t.value for t in AtomType}:
        return None

    atom_type = AtomType(atom_type_raw)
    source_sentence = resolve_source_sentence(str(item.get("source_sentence") or "").strip(), full_text)
    if not source_sentence:
        return None

    domain_raw = normalize_extraction_domain(item.get("domain"))

    atom_source = str(item.get("atom_source") or "").strip()
    if not atom_source:
        return None

    payload_raw = item.get("payload")
    if not isinstance(payload_raw, dict):
        payload_raw = {k: v for k, v in item.items() if k not in {
            "atom_type", "source_sentence", "atom_source", "domain", "fact_confidence", "verified",
        }}

    normalized_payload = normalize_extraction_payload(
        atom_type,
        payload_raw,
        source_sentence=source_sentence,
        atom_source=atom_source,
    )
    if normalized_payload is None:
        return None

    try:
        payload = payload_from_dict(atom_type, normalized_payload)
    except (TypeError, ValueError, ValidationError):
        return None

    try:
        fact_confidence = float(item.get("fact_confidence", 0.7))
    except (TypeError, ValueError):
        fact_confidence = 0.7
    fact_confidence = max(0.0, min(1.0, fact_confidence))

    return AtomCreate(
        content_id=content_id,
        source_url=source_url,
        source_sentence=source_sentence,
        domain=Domain(domain_raw),
        atom_source=atom_source,
        source_credibility=resolve_credibility(atom_source),
        fact_confidence=fact_confidence,
        verified=False,
        atom_type=atom_type,
        payload=payload,
    )


__all__ = ["build_extraction_prompt", "parse_llm_atoms"]
