"""Shared presentation policy for event highlights."""

from __future__ import annotations

import re
from typing import Any, Mapping


NEED_TO_KNOW_IMPORTANCE_THRESHOLD = 70.0
NEED_TO_KNOW_INCREMENTAL_THRESHOLD = 45.0
NEED_TO_KNOW_CONFIDENCE_THRESHOLD = 55.0

_MAX_EVENT_NAME_CJK_CHARS = 28
_MAX_EVENT_NAME_LATIN_WORDS = 10
_LEADING_LABEL_RE = re.compile(r"^(?:\s*[【\[][^【】\[\]]{1,12}[】\]]\s*)+")
_LEADING_EDITORIAL_RE = re.compile(
    r"^(?:早报|晚报|午报|快讯|独家|深度|解读|观察|评论|一文(?:读懂|看懂))\s*[：:|｜·-]*\s*"
)
_ATTRIBUTION_RE = re.compile(
    r"(?:[，,；;]|\s)\s*(?:机构|专家|分析师|业内人士|知情人士|媒体|报告)"
    r"(?:称|认为|指出|表示|预计|判断).*$"
)
_SENSATIONAL_LEAD_RE = re.compile(r"(?:真正大敌|重磅|震惊|炸裂|突发|罕见|真相|必看)")
_EDITORIAL_LEAD_RE = re.compile(r"^(?:以|如何|为何|为什么|一文)\S*")


def is_need_to_know_event(
    *,
    importance: float,
    incremental: float,
    confidence: float,
) -> bool:
    """Return whether an event meets the public "must see" contract."""

    return (
        importance >= NEED_TO_KNOW_IMPORTANCE_THRESHOLD
        and incremental >= NEED_TO_KNOW_INCREMENTAL_THRESHOLD
        and confidence >= NEED_TO_KNOW_CONFIDENCE_THRESHOLD
    )


def classify_event_section(
    *,
    importance: float,
    incremental: float,
    confidence: float,
    corroboration_tier: str | None,
) -> str:
    if is_need_to_know_event(
        importance=importance,
        incremental=incremental,
        confidence=confidence,
    ):
        return "need_to_know"
    if incremental >= 45 or corroboration_tier in {"single_low", "single_high"}:
        return "brewing"
    return "later"


def _truncate_event_name(title: str) -> str:
    if not title:
        return "未命名事件"

    if re.search(r"[\u4e00-\u9fff]", title):
        if len(title) <= _MAX_EVENT_NAME_CJK_CHARS:
            return title
        prefix = title[: _MAX_EVENT_NAME_CJK_CHARS]
        cut = max(prefix.rfind(mark) for mark in ("，", ",", "；", ";", "：", ":"))
        if cut >= 10:
            prefix = prefix[:cut]
        return prefix.rstrip("，,；;：:、 ")

    words = title.split()
    if len(words) <= _MAX_EVENT_NAME_LATIN_WORDS:
        return title
    return " ".join(words[:_MAX_EVENT_NAME_LATIN_WORDS]).rstrip(".,;:-")


def simplify_event_name(title: str) -> str:
    """Turn a source headline into a compact, non-sensational event label."""

    value = " ".join(str(title or "").split()).strip()
    value = _LEADING_LABEL_RE.sub("", value)
    value = _LEADING_EDITORIAL_RE.sub("", value)
    value = _ATTRIBUTION_RE.sub("", value)

    # Article headlines often append commentary after these separators. Keep
    # the factual lead when it is substantial enough to stand on its own.
    separators = [separator for separator in ("——", "！", "!", "？", "?") if separator in value]
    if separators:
        separator = min(separators, key=value.index)
        lead, _found, tail = value.partition(separator)
        lead = lead.strip()
        tail = tail.strip()
        if len(lead) >= 6:
            if len(tail) >= 6 and (
                _SENSATIONAL_LEAD_RE.search(lead)
                or (separator == "——" and _EDITORIAL_LEAD_RE.search(lead))
            ):
                value = tail
            else:
                value = lead

    value = value.replace("愈演愈烈", "升级")

    value = value.strip("-—_｜|:：,，;；.!！?？ ")
    return _truncate_event_name(value)


def event_name_from_cluster(primary: Mapping[str, Any], cluster: Mapping[str, Any]) -> str:
    """Prefer an explicit event name, otherwise derive one from the lead report."""

    raw = (
        cluster.get("event_name")
        or primary.get("translated_title")
        or primary.get("title")
        or cluster.get("topic")
        or "未命名事件"
    )
    return simplify_event_name(str(raw))


__all__ = [
    "NEED_TO_KNOW_CONFIDENCE_THRESHOLD",
    "NEED_TO_KNOW_IMPORTANCE_THRESHOLD",
    "NEED_TO_KNOW_INCREMENTAL_THRESHOLD",
    "classify_event_section",
    "event_name_from_cluster",
    "is_need_to_know_event",
    "simplify_event_name",
]
