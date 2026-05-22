"""Coerce LLM extraction payloads before strict Pydantic validation."""

from __future__ import annotations

from typing import Any

from app.domains.atoms.vocab import (
    AtomType,
    DataSourceType,
    Domain,
    Intensity,
    PeriodType,
    Role,
    Sentiment,
    SubjectType,
    Unit,
    Validity,
    WhatType,
)

_SUBJECT_TYPE_ALIASES: dict[str, str] = {
    "公司": SubjectType.COMPANY.value,
    "企业": SubjectType.COMPANY.value,
    "corporation": SubjectType.COMPANY.value,
    "company": SubjectType.COMPANY.value,
    "政府": SubjectType.GOVERNMENT.value,
    "政府机构": SubjectType.GOVERNMENT.value,
    "government": SubjectType.GOVERNMENT.value,
    "人物": SubjectType.PERSON.value,
    "个人": SubjectType.PERSON.value,
    "person": SubjectType.PERSON.value,
    "机构": SubjectType.ORGANIZATION.value,
    "组织": SubjectType.ORGANIZATION.value,
    "organization": SubjectType.ORGANIZATION.value,
    "人群": SubjectType.ORGANIZATION.value,
    "国家": SubjectType.REGION.value,
    "国家/地区": SubjectType.REGION.value,
    "region": SubjectType.REGION.value,
    "产品": SubjectType.PRODUCT.value,
    "品牌": SubjectType.PRODUCT.value,
    "product": SubjectType.PRODUCT.value,
}

_VALID_SUBJECT_TYPES = {t.value for t in SubjectType}
_VALID_WHAT_TYPES = {t.value for t in WhatType}
_VALID_VALIDITIES = {t.value for t in Validity}
_VALID_ROLES = {t.value for t in Role}
_VALID_SENTIMENTS = {t.value for t in Sentiment}
_VALID_INTENSITIES = {t.value for t in Intensity}
_VALID_DATA_SOURCE_TYPES = {t.value for t in DataSourceType}
_VALID_UNITS = {t.value for t in Unit}
_VALID_PERIOD_TYPES = {t.value for t in PeriodType}


def _pick_enum(raw: Any, allowed: set[str], default: str) -> str:
    text = str(raw or "").strip()
    if text in allowed:
        return text
    return default


def _non_empty_str(raw: Any, fallback: str) -> str:
    text = str(raw or "").strip()
    return text or fallback


def _normalize_who(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    entries: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        type_raw = str(item.get("type") or "").strip()
        subject_type = _SUBJECT_TYPE_ALIASES.get(type_raw, type_raw)
        if subject_type not in _VALID_SUBJECT_TYPES:
            subject_type = SubjectType.ORGANIZATION.value
        entries.append({"name": name, "type": subject_type})
    return entries


def _summary_from_sentence(source_sentence: str, *, limit: int = 200) -> str:
    text = " ".join((source_sentence or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def normalize_extraction_payload(
    atom_type: AtomType,
    raw: dict[str, Any],
    *,
    source_sentence: str,
    atom_source: str,
) -> dict[str, Any] | None:
    """Return a payload dict suitable for :func:`payload_from_dict`, or ``None`` if unsalvageable."""
    data = dict(raw or {})
    summary = _summary_from_sentence(source_sentence)

    if atom_type == AtomType.INFO:
        who = _normalize_who(data.get("who"))
        if not who:
            who = [{"name": atom_source or "未知", "type": SubjectType.ORGANIZATION.value}]
        entities_raw = data.get("entities")
        entities: list[str] = []
        if isinstance(entities_raw, list):
            entities = [str(x).strip() for x in entities_raw if str(x).strip()]
        if not entities:
            entities = [entry["name"] for entry in who[:3]]
        return {
            "when": data.get("when"),
            "where": data.get("where"),
            "who": who,
            "why": data.get("why"),
            "what_type": _pick_enum(data.get("what_type"), _VALID_WHAT_TYPES, WhatType.OTHER.value),
            "what": _non_empty_str(data.get("what"), summary),
            "how": data.get("how"),
            "result": data.get("result"),
            "entities": entities,
            "validity": _pick_enum(data.get("validity"), _VALID_VALIDITIES, Validity.MEDIUM.value),
        }

    if atom_type == AtomType.OPINION:
        who = _normalize_who(data.get("who"))
        if not who:
            who = [{"name": atom_source or "未知", "type": SubjectType.PERSON.value}]
        return {
            "who": who,
            "role": _pick_enum(data.get("role"), _VALID_ROLES, Role.OTHER.value),
            "say_what": _non_empty_str(data.get("say_what"), summary),
            "is_quote": bool(data.get("is_quote", False)),
            "context": data.get("context"),
            "sentiment": _pick_enum(data.get("sentiment"), _VALID_SENTIMENTS, Sentiment.NEUTRAL.value),
            "intensity": _pick_enum(data.get("intensity"), _VALID_INTENSITIES, Intensity.CLEAR.value),
            "political_spectrum": data.get("political_spectrum"),
            "china_stance": data.get("china_stance"),
        }

    try:
        value = float(data.get("value"))
    except (TypeError, ValueError):
        return None

    metric = _non_empty_str(data.get("metric"), "")
    if not metric:
        return None

    return {
        "source_org": _non_empty_str(data.get("source_org"), atom_source or "未知"),
        "source_type": _pick_enum(
            data.get("source_type"),
            _VALID_DATA_SOURCE_TYPES,
            DataSourceType.MEDIA_COMPILED.value,
        ),
        "metric": metric,
        "value": value,
        "unit": _pick_enum(data.get("unit"), _VALID_UNITS, Unit.CUSTOM.value),
        "caliber": data.get("caliber"),
        "period": _non_empty_str(data.get("period"), "未知"),
        "period_type": _pick_enum(data.get("period_type"), _VALID_PERIOD_TYPES, PeriodType.AS_OF.value),
        "is_relative": bool(data.get("is_relative", False)),
        "base_value": data.get("base_value"),
        "base_period": data.get("base_period"),
        "validity": _pick_enum(data.get("validity"), _VALID_VALIDITIES, Validity.SHORT.value),
    }


def normalize_extraction_domain(raw: Any) -> str:
    text = str(raw or Domain.OTHER.value).strip()
    if text in {d.value for d in Domain}:
        return text
    return Domain.OTHER.value


__all__ = ["normalize_extraction_domain", "normalize_extraction_payload"]
