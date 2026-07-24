"""Deterministic Event Signature v1 extraction with evidence spans."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any

from app.domains.events.config import event_config


_DATE_RE = re.compile(r"\b(20\d{2})[-/.年](0?[1-9]|1[0-2])[-/.月](0?[1-9]|[12]\d|3[01])日?\b")
_VERSION_RE = re.compile(r"\b(?:v(?:ersion)?\s*)(\d+(?:\.\d+){1,3})(?:[-_ ]?(alpha|beta|rc\d*))?\b", re.I)
_IDENTIFIER_RE = re.compile(
    r"\b(?:case|bill|act|flight|法案|案件|航班|编号)[\s:#-]*([A-Z]{0,5}\d[\w.-]{1,20})\b",
    re.I,
)
_MONEY_RE = re.compile(r"(?:(US\$|S\$|HK\$|￥|¥|€|£|\$)\s?([\d,.]+(?:\s?(?:million|billion|万|亿))?))", re.I)
_PERCENT_RE = re.compile(r"(?<!\w)(\d+(?:\.\d+)?)\s?(%|％|percent|个百分点)", re.I)
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9._-]{2,}|[\u4e00-\u9fff]{2,8}")

_ACTIONS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("deny", ("deny", "denies", "denied", "否认", "驳斥"), "negative"),
    ("retract", ("retract", "retracted", "撤回", "撤销"), "negative"),
    ("confirm", ("confirm", "confirmed", "证实", "确认"), "positive"),
    ("launch", ("launch", "launched", "release", "released", "发布", "推出", "上线"), "positive"),
    ("approve", ("approve", "approved", "批准", "通过"), "positive"),
    ("acquire", ("acquire", "acquired", "收购"), "positive"),
    ("sue", ("sue", "sued", "lawsuit", "起诉", "诉讼"), "neutral"),
    ("investigate", ("investigate", "investigation", "调查"), "neutral"),
    ("plan", ("plan", "plans", "planned", "计划", "拟"), "neutral"),
)
_MODALITY: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("denied", ("deny", "denies", "denied", "否认", "驳斥")),
    ("question", ("?", "？", "是否", "will ", "could ")),
    ("alleged", ("alleged", "accused", "被指", "涉嫌")),
    ("planned", ("plan", "plans", "planned", "计划", "拟", "将于")),
    ("reported", ("reportedly", "sources say", "据报", "消息称", "据称", "传闻")),
    ("confirmed", ("official", "announced", "confirmed", "官方", "宣布", "证实", "确认")),
)
_STOP_ENTITIES = {
    "about", "after", "before", "could", "from", "have", "into", "more", "report",
    "said", "says", "that", "their", "this", "with", "will", "消息", "报道", "今日",
    "表示", "宣布", "发布", "计划", "确认", "公司", "相关", "已经",
}
_LOCATIONS = {
    "beijing": "Beijing",
    "北京": "Beijing",
    "shanghai": "Shanghai",
    "上海": "Shanghai",
    "singapore": "Singapore",
    "新加坡": "Singapore",
    "washington": "Washington",
    "华盛顿": "Washington",
    "london": "London",
    "伦敦": "London",
    "tokyo": "Tokyo",
    "东京": "Tokyo",
    "hong kong": "Hong Kong",
    "香港": "Hong Kong",
}


def _evidence(kind: str, value: str, text: str) -> dict[str, Any]:
    start = text.lower().find(value.lower())
    return {"field": kind, "text": value, "start": max(0, start), "end": max(0, start) + len(value)}


def _language(text: str) -> str:
    zh = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if zh > latin / 2:
        return "zh"
    if latin:
        return "en"
    return "unknown"


def _normalized_date(match: re.Match[str]) -> tuple[str, datetime | None]:
    value = f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    try:
        return value, datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return value, None


def extract_event_signature(
    *,
    title: str,
    summary: str | None = None,
    publish_time: datetime | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract a replayable rules-only signature; low-confidence fields stay empty."""

    title = (title or "").strip()
    lede = (summary or "").strip()
    text = " ".join(part for part in (title, lede[:800]) if part)
    lower = text.lower()
    evidence: list[dict[str, Any]] = []

    dates: list[str] = []
    event_time = None
    for match in _DATE_RE.finditer(text):
        value, parsed = _normalized_date(match)
        if value not in dates:
            dates.append(value)
            evidence.append(_evidence("event_time", match.group(0), text))
        event_time = event_time or parsed
    if event_time is None:
        event_time = publish_time

    identifiers: list[dict[str, Any]] = []
    for match in _IDENTIFIER_RE.finditer(text):
        value = match.group(1).upper()
        identifiers.append({"type": "canonical_identifier", "value": value})
        evidence.append(_evidence("identifiers", match.group(0), text))
    for match in _VERSION_RE.finditer(text):
        value = match.group(1)
        suffix = (match.group(2) or "").lower()
        normalized = f"{value}-{suffix}" if suffix else value
        identifiers.append({"type": "version", "value": normalized})
        evidence.append(_evidence("identifiers", match.group(0), text))

    quantities: list[dict[str, Any]] = []
    for match in _MONEY_RE.finditer(text):
        quantities.append({"type": "money", "unit": match.group(1), "value": match.group(2).replace(",", "")})
        evidence.append(_evidence("quantities", match.group(0), text))
    for match in _PERCENT_RE.finditer(text):
        quantities.append({"type": "percent", "unit": match.group(2), "value": match.group(1)})
        evidence.append(_evidence("quantities", match.group(0), text))

    action = {"lemma": "", "surface": "", "polarity": "neutral"}
    for lemma, surfaces, polarity in _ACTIONS:
        surface = next((candidate for candidate in surfaces if candidate.lower() in lower), None)
        if surface:
            action = {"lemma": lemma, "surface": surface, "polarity": polarity}
            evidence.append(_evidence("trigger_action", surface, text))
            break

    modality = "reported"
    for candidate, markers in _MODALITY:
        if any(marker.lower() in lower for marker in markers):
            modality = candidate
            break

    location: dict[str, Any] = {}
    for marker, canonical in _LOCATIONS.items():
        if marker in lower:
            location = {"canonical_id": canonical.lower().replace(" ", "-"), "name": canonical}
            evidence.append(_evidence("location", marker, text))
            break

    words = [match.group(0) for match in _WORD_RE.finditer(title)]
    entities: list[dict[str, Any]] = []
    for word in words:
        normalized = word.strip("._-").lower()
        if normalized in _STOP_ENTITIES or len(normalized) < 2:
            continue
        canonical_id = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", normalized).strip("-")
        if not canonical_id or any(row["canonical_id"] == canonical_id for row in entities):
            continue
        entities.append({"canonical_id": canonical_id, "surface": word, "type": "unknown"})
        evidence.append(_evidence("normalized_entities", word, text))
        if len(entities) >= 8:
            break

    meta = metadata if isinstance(metadata, dict) else {}
    duplicate_group = str(meta.get("duplicate_group_id") or "").strip()
    if duplicate_group:
        identifiers.append({"type": "duplicate_group", "value": duplicate_group})

    facts = {
        "dates": dates,
        "identifiers": sorted(identifiers, key=lambda row: (row["type"], row["value"])),
        "quantities": sorted(quantities, key=lambda row: (row["type"], row["value"])),
        "action": action,
        "modality": modality,
        "location": location,
        "entities": entities,
    }
    fingerprint = hashlib.sha256(
        json.dumps(facts, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    populated = sum(bool(facts[key]) for key in ("dates", "identifiers", "quantities", "location", "entities"))
    if action["lemma"]:
        populated += 1
    confidence = min(0.95, 0.35 + 0.08 * populated)
    return {
        "signature_version": event_config().signature_version,
        "normalized_entities": entities,
        "actors": entities[:2],
        "trigger_action": action,
        "object": entities[2] if len(entities) > 2 else {},
        "location": location,
        "event_time_start": event_time,
        "event_time_end": event_time,
        "event_time_precision": "day" if dates else ("publish_time" if publish_time else None),
        "quantities": quantities,
        "identifiers": identifiers,
        "outcomes": [],
        "modality": modality,
        "source_claim_type": "official" if modality == "confirmed" and "官方" in text else "report",
        "language": _language(text),
        "source_text": {"title": title, "lede": lede[:800], "main_event": text[:1000]},
        "confidence": round(confidence, 3),
        "extraction_method": "rules",
        "model_version": None,
        "evidence_spans": evidence,
        "fingerprint": fingerprint,
    }


def signature_facts(signature: dict[str, Any]) -> list[dict[str, Any]]:
    """Return normalized facts used by Snapshot meaningful-change detection."""

    facts: list[dict[str, Any]] = []
    action = signature.get("trigger_action") or {}
    if action.get("lemma"):
        facts.append({"kind": "action", "value": action.get("lemma"), "polarity": action.get("polarity")})
    for entity in signature.get("normalized_entities") or []:
        facts.append({"kind": "entity", "value": entity.get("canonical_id")})
    for identifier in signature.get("identifiers") or []:
        facts.append({"kind": identifier.get("type") or "identifier", "value": identifier.get("value")})
    for quantity in signature.get("quantities") or []:
        facts.append(
            {
                "kind": quantity.get("type") or "quantity",
                "value": quantity.get("value"),
                "unit": quantity.get("unit"),
            }
        )
    location = signature.get("location") or {}
    if location.get("canonical_id"):
        facts.append({"kind": "location", "value": location.get("canonical_id")})
    if signature.get("modality"):
        facts.append({"kind": "modality", "value": signature.get("modality")})
    return sorted(facts, key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True))


__all__ = ["extract_event_signature", "signature_facts"]
