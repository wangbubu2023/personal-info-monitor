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


def format_event_presentation(
    *,
    event_data: dict[str, Any],
    full_reports: bool = False,
) -> dict[str, Any]:
    """根据 full_reports 参数返回 Curated 精选视图或 Full 全量历史视图。
    默认接口必须为 Curated (精选 3 条 Highlights，不直接暴露庞大 Timeline)。
    """
    curated = {
        "event_id": event_data.get("id"),
        "title": simplify_event_name(event_data.get("title", "")),
        "summary": event_data.get("summary", ""),
        "status": event_data.get("status", "active"),
        "canonical_url": event_data.get("canonical_url"),
        "created_at": event_data.get("created_at"),
    }

    reports = event_data.get("reports", [])
    if full_reports:
        curated["timeline"] = reports
        curated["view_mode"] = "full"
    else:
        curated["timeline"] = reports[:3] if isinstance(reports, list) else []
        curated["view_mode"] = "curated"

    return curated


def export_event_to_markdown(
    *,
    title: str,
    summary: str,
    source_url: str,
    full_body: str | None = None,
    is_paid_source: bool = False,
) -> str:
    """生成 Markdown 导出的文本。
    合规准则: 如果是付费源 (is_paid_source=True)，绝对滤除无权再分发的付费全文 (full_body)。
    """
    md_lines = [
        f"# {title}",
        "",
        "## 摘要",
        summary,
        "",
        f"- **原文链接**: {source_url}",
    ]

    if is_paid_source:
        md_lines.extend([
            "",
            "> [!NOTE]",
            "> 该内容源自受权/付费源，根据版权再分发保护协议，已自动过滤付费全文，仅保留结构化摘要与原文出处链接。",
        ])
    elif full_body:
        md_lines.extend([
            "",
            "## 正文",
            full_body,
        ])

    return "\n".join(md_lines)


__all__ = [
    "NEED_TO_KNOW_CONFIDENCE_THRESHOLD",
    "NEED_TO_KNOW_IMPORTANCE_THRESHOLD",
    "NEED_TO_KNOW_INCREMENTAL_THRESHOLD",
    "classify_event_section",
    "event_name_from_cluster",
    "export_event_to_markdown",
    "format_event_presentation",
    "is_need_to_know_event",
    "simplify_event_name",
]
