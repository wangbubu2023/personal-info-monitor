"""Text-level utilities for the hourly digest pipeline.

Pure helpers (no DB, no network): text cleaning, category classification,
title formatting, limit coercion, and the system-settings lookups used
to drive digest generation.
"""

from __future__ import annotations

import html
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from app.platform.config.system_settings import (
    get_system_settings_sync,
    normalize_hourly_digest_window_hours,
)
from app.utils.datetime import user_timezone


SYSTEM_TZ = user_timezone()


def local_to_utc_naive(dt_local: datetime) -> datetime:
    """Convert a local (Shanghai-anchored) datetime to naive UTC."""
    return dt_local.astimezone(timezone.utc).replace(tzinfo=None)


def format_digest_title(target_label_local: datetime, *, window_hours: int = 1) -> str:
    window_hours = max(1, int(window_hours or 1))
    if window_hours <= 1:
        return f"{target_label_local.month} 月 {target_label_local.day} 日 {target_label_local.hour} 时简报"

    start_local = target_label_local - timedelta(hours=window_hours)
    if start_local.date() == target_label_local.date():
        return (
            f"{target_label_local.month} 月 {target_label_local.day} 日 "
            f"{start_local.hour}-{target_label_local.hour} 时简报"
        )
    return (
        f"{start_local.month} 月 {start_local.day} 日 {start_local.hour} 时-"
        f"{target_label_local.month} 月 {target_label_local.day} 日 {target_label_local.hour} 时简报"
    )


def coerce_limit_int(value: Any, default: int, *, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(min_value, min(max_value, parsed))


def get_digest_limits() -> dict:
    settings = get_system_settings_sync() or {}
    limits = settings.get("limits") if isinstance(settings, dict) else {}
    limits = limits if isinstance(limits, dict) else {}
    return {
        "max_input_items": coerce_limit_int(
            limits.get("max_hourly_digest_input_items"),
            200,
            min_value=20,
            max_value=2000,
        ),
        "max_candidates": coerce_limit_int(
            limits.get("max_digest_candidates"),
            12,
            min_value=3,
            max_value=30,
        ),
    }


def hourly_digest_user_settings() -> dict:
    s = get_system_settings_sync() or {}
    hd = s.get("hourly_digest")
    return hd if isinstance(hd, dict) else {}


def get_digest_window_hours() -> int:
    return normalize_hourly_digest_window_hours(get_system_settings_sync() or {})


def strip_ranking_internal(item: dict) -> dict:
    """Drop ranking-internal debug fields (prefix ``_``) before handing off to LLM/UI."""
    return {k: v for k, v in item.items() if not str(k).startswith("_")}


def clean_digest_text(text: str) -> str:
    """Collapse whitespace, strip wire-service / byline-style prefixes."""
    cleaned = html.unescape((text or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"^[A-Za-z][A-Za-z0-9 .&/'()_-]{1,80}:\s*", "", cleaned)
    cleaned = re.sub(
        r"^[A-Za-z][A-Za-z0-9 .&/'()_-]{1,80}\s*/\s*[A-Za-z][A-Za-z0-9 .&/'()_-]{1,80}:\s*",
        "",
        cleaned,
    )
    return cleaned.strip()


_REASONING_TAG_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Closed blocks: <think>...</think>, <reasoning>...</reasoning>, <scratchpad>..., <analysis>...
    re.compile(r"<(?:think|reasoning|scratchpad|analysis)\b[^>]*>.*?</(?:think|reasoning|scratchpad|analysis)>",
               flags=re.IGNORECASE | re.DOTALL),
    # Open-ended: a leading <think> with no close eats everything up to first "## " heading or to end.
    re.compile(r"^\s*<(?:think|reasoning|scratchpad|analysis)\b[^>]*>.*?(?=(?:^|\n)##\s|\Z)",
               flags=re.IGNORECASE | re.DOTALL | re.MULTILINE),
    # Stray closing tag left behind by half-broken outputs.
    re.compile(r"</(?:think|reasoning|scratchpad|analysis)>\s*",
               flags=re.IGNORECASE),
)


def strip_llm_reasoning(body: str) -> str:
    """Remove ``<think>…</think>`` / ``<reasoning>…</reasoning>`` scratchpads.

    Some reasoning-tuned providers (DeepSeek-R1, MiniMax-M2 thinking variants,
    Qwen-3 reasoning) leak their chain-of-thought wrapped in one of these XML
    tags. We strip them before validation so the stored digest stays clean.
    """
    if not body:
        return body
    out = body
    for pat in _REASONING_TAG_PATTERNS:
        out = pat.sub("", out)
    # Also strip any triple-backtick fences the model may have added against the
    # prompt's "禁止代码围栏" rule — they hide valid digest content from the format
    # validator.
    out = re.sub(r"```[\w-]*\s*\n", "", out)
    out = out.replace("```", "")
    return out.strip()


def preferred_item_title(item: dict) -> str:
    return clean_digest_text(
        (item.get("translated_title") or "").strip()
        or (item.get("original_title") or "").strip()
        or (item.get("title") or "").strip()
        or "未命名事件"
    )


def preferred_item_summary(item: dict) -> str:
    text = clean_digest_text(
        (item.get("translated_summary") or "").strip()
        or (item.get("summary") or "").strip()
    )
    if len(text) > 120:
        return f"{text[:117]}..."
    return text or "该事件在本次简报窗口内出现新的进展。"


def normalize_digest_category(label: str) -> str:
    normalized = (label or "").strip()
    return normalized or "重点"


_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("AI", (" ai", "openai", "anthropic", "gemini", "llm", "model", "人工智能", "大模型", "智能体")),
    ("汽车", ("car", "auto", "ev", "tesla", "byd", "蔚来", "小鹏", "理想", "汽车")),
    ("金融", ("bank", "bond", "fund", "insurance", "credit", "融资租赁", "证券", "基金", "保险", "信贷")),
    ("财经", ("ipo", "earnings", "economy", "market", "acquisition", "merger", "export", "revenue", "profit", "股价", "财报", "经济", "出口")),
    ("科技", ("tech", "startup", "chip", "semiconductor", "software", "app", "cloud", "developer", "科技", "芯片", "半导体")),
    ("政策", ("ministry", "government", "policy", "regulator", "外交部", "国务院", "部委", "政策", "监管")),
    ("国际", ("war", "iran", "ukraine", "pakistan", "india", "china", "eu", "外交", "国际", "冲突")),
)


def classify_digest_category(text: str) -> str:
    """Rule-based fallback classifier used when the LLM picks ``重点``.

    ASCII tokens (``ai``, ``ev``, ``car``) match only on whole-word
    boundaries to avoid false positives inside ``airbnb`` / ``available``.
    CJK / Unicode keywords match as substrings.
    """
    normalized = (text or "").lower()
    ascii_tokens = set(re.findall(r"[a-z0-9.+-]+", normalized))

    def _matches(keyword: str) -> bool:
        token = (keyword or "").strip().lower()
        if not token:
            return False
        if re.fullmatch(r"[a-z0-9.+-]+", token):
            return token in ascii_tokens
        return token in normalized

    for label, keywords in _CATEGORY_RULES:
        if any(_matches(keyword) for keyword in keywords):
            return label
    return "重点"


def hourly_digest_skip_format_validation() -> bool:
    """When enabled, accept any non-empty LLM digest (skip ### / 来源： /reader/ gate).

    Set ``PIM_HOURLY_DIGEST_SKIP_FORMAT_VALIDATION=true`` to inspect raw model output
    without code edits.
    """
    raw = os.environ.get("PIM_HOURLY_DIGEST_SKIP_FORMAT_VALIDATION", "false").strip().lower()
    return raw in {"1", "true", "yes", "on"}


_DIGEST_SECTION_HEADINGS = (
    "### 需要你现在知道",
    "### 正在发酵",
    "### 可稍后看",
)

_LLM_META_REASONING_MARKERS = (
    "首先，用户要求",
    "首先，任务是",
    "用户要求我",
    "我需要",
    "我必须",
    "我们需要",
    "关键点：",
    "the user asks",
    "i need to",
    "we need to",
)


def is_valid_digest_format(
    body: str,
    *,
    expected_title: str | None = None,
    require_reader_link: bool = False,
) -> bool:
    """Validate the complete public briefing contract before persistence.

    Merely containing Markdown markers is insufficient: leaked model
    scratchpads repeat prompt examples and therefore used to pass the old
    substring check.  Require the actual title/summary/section sequence and
    reject common meta-reasoning language.
    """

    text = (body or "").strip()
    if not text:
        return False
    if hourly_digest_skip_format_validation():
        return True
    if len(text) > 8000:
        return False
    if require_reader_link and "/reader/" not in text:
        return False

    folded = text.casefold()
    if any(marker.casefold() in folded for marker in _LLM_META_REASONING_MARKERS):
        return False

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 5:
        return False

    expected_heading = f"## {expected_title.strip()}" if expected_title else None
    if expected_heading:
        if lines[0] != expected_heading:
            return False
    elif not re.fullmatch(r"##\s+\S.*", lines[0]):
        return False

    if not lines[1].startswith("一句话："):
        return False

    h2_lines = [line for line in lines if line.startswith("## ")]
    if h2_lines != [lines[0]]:
        return False
    h3_lines = [line for line in lines if line.startswith("### ")]
    if h3_lines != list(_DIGEST_SECTION_HEADINGS):
        return False

    positions = [lines.index(heading) for heading in _DIGEST_SECTION_HEADINGS]
    return positions == sorted(positions) and positions[0] > 1


ORDERED_DIGEST_CATEGORIES: tuple[str, ...] = (
    "重点",
    "财经",
    "金融",
    "科技",
    "AI",
    "汽车",
    "政策",
    "国际",
)
