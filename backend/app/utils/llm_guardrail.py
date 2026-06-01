"""Guardrails for LLM output before it is stored or shown to users.

Two independent LLM pipelines (hourly digest synthesis and the translator)
historically trusted raw model output and wrote it straight to the database.
That let two failure modes through:

* **Refusals / self-introductions** — the model answers "抱歉，我无法…" or
  "As an AI assistant…" instead of doing the task, and the apology gets stored
  as if it were a translation / digest item.
* **Hallucinations** — the model invents facts (dates, numbers, whole stories)
  that are not present in the source material.

The helpers here are deliberately conservative: they only fire on signals that
almost never occur in legitimate output, so wiring them in does not silently
drop good content. In particular refusal detection keys off *first-person
assistant identity* phrases rather than topical words like "prompt injection"
— the latter routinely appear in legitimate security-news translations.

Every check returns ``None`` when the text looks fine, or a short reason string
when it should be rejected, so callers can log the reason uniformly.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

# --- Refusal / self-introduction detection ---------------------------------
#
# Scoped to first-person assistant identity + inability phrasing. We do NOT
# match bare topical terms ("提示注入" / "prompt injection") because those are
# valid article content that gets translated all the time.
_REFUSAL_PATTERNS_ZH = (
    r"抱歉[，,]?\s*(?:我|本\s*AI|本助手)[^。\n]{0,20}?(?:无法|不能|不会)",
    r"作为(?:一个|一名)?\s*(?:AI|人工智能|文本)\s*(?:语言)?\s*(?:模型|助手)",
    r"我是(?:一个|一名)?\s*(?:AI|人工智能|文本)\s*(?:语言)?\s*(?:模型|助手)",
    r"我(?:无法|不能|不会)(?:执行|帮助|协助|完成|进行|提供|删除|修改|操作)",
    r"我不会忽略(?:我的|您的)?(?:系统)?指令",
)
_REFUSAL_PATTERNS_EN = (
    r"^\s*(?:i\s*'?m\s+sorry|i\s+am\s+sorry|sorry[,.]?\s+(?:but\s+)?i)\b",
    r"^\s*i\s+(?:can(?:not|'?t)|am\s+unable\s+to|won'?t)\b",
    r"\bas\s+an?\s+(?:ai|artificial\s+intelligence)\s+(?:assistant|model|language\s+model)\b",
    r"\bi\s+(?:cannot|can'?t|am\s+unable\s+to)\s+(?:help|assist|fulfil|fulfill|comply|complete|perform)\b",
    r"\bi\s+(?:am|'m)\s+(?:just|only)?\s*an?\s+(?:ai|language\s+model|text\s+ai)\b",
)
_REFUSAL_RE = [re.compile(p, re.IGNORECASE) for p in _REFUSAL_PATTERNS_ZH + _REFUSAL_PATTERNS_EN]

_DATE_RE = re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]")

_EN_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_EN_DATE_MD_RE = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})\b",
    re.IGNORECASE,
)
_EN_DATE_DM_RE = re.compile(
    r"\b(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b",
    re.IGNORECASE,
)


def _chinese_dates(text: str) -> set[tuple[int, int]]:
    out: set[tuple[int, int]] = set()
    for m, d in _DATE_RE.findall(text):
        out.add((int(m), int(d)))
    return out


def _english_dates(text: str) -> set[tuple[int, int]]:
    out: set[tuple[int, int]] = set()
    for mon, d in _EN_DATE_MD_RE.findall(text):
        out.add((_EN_MONTHS[mon[:3].lower()], int(d)))
    for d, mon in _EN_DATE_DM_RE.findall(text):
        out.add((_EN_MONTHS[mon[:3].lower()], int(d)))
    return out


def detect_llm_refusal(text: str) -> Optional[str]:
    """Return a reason when ``text`` looks like an LLM refusal/self-intro.

    Only the leading window is inspected: genuine refusals lead with the
    apology/identity statement, while legitimate output that merely *mentions*
    an assistant later on is left alone.
    """
    if not text:
        return None
    head = text.strip()[:240]
    if len(head) < 6:
        return None
    for pat in _REFUSAL_RE:
        m = pat.search(head)
        if m:
            return f"refusal:{pat.pattern[:48]}"
    return None


def check_translation_ratio(
    src: str,
    translated: str,
    *,
    max_ratio: float = 2.5,
    min_ratio: float = 0.25,
) -> Optional[str]:
    """Reject translations whose length is wildly off from the source.

    Bounds are intentionally loose — CJK<->Latin expansion/compression is real
    — so this only catches gross anomalies (e.g. a 60-char title turning into a
    228-char apology, ~3.8x).
    """
    if not src or not translated:
        return None
    src_len = len(src.strip())
    out_len = len(translated.strip())
    # Short sources (titles, snippets) have noisy ratios; only judge longer text.
    if src_len < 16:
        return None
    ratio = out_len / max(1, src_len)
    if ratio > max_ratio:
        return f"too_long({ratio:.2f}x)"
    if ratio < min_ratio:
        return f"too_short({ratio:.2f}x)"
    return None


def _char_ngrams(text: str, n: int = 3) -> set[str]:
    cleaned = re.sub(r"\s+", "", text.lower())
    if len(cleaned) < n:
        return {cleaned} if cleaned else set()
    return {cleaned[i : i + n] for i in range(len(cleaned) - n + 1)}


def check_grounding(
    output: str,
    source_text: str,
    *,
    threshold: float = 0.25,
    n: int = 3,
    min_output_chars: int = 12,
    min_source_chars: int = 24,
) -> Optional[str]:
    """Reject output that shares too little char-n-gram material with source.

    Uses *containment* (share of the output's n-grams found in the source),
    not symmetric Jaccard: the source is usually much longer than the output,
    and Jaccard would punish every short summary regardless of grounding. A
    faithful rewrite reuses entities/terms from the source and scores high; a
    fabricated story scores near zero.

    Returns ``None`` (skip) when either side is too short to judge.
    """
    if not output or not source_text:
        return None
    if len(re.sub(r"\s+", "", output)) < min_output_chars:
        return None
    if len(re.sub(r"\s+", "", source_text)) < min_source_chars:
        return None
    out_ngrams = _char_ngrams(output, n)
    src_ngrams = _char_ngrams(source_text, n)
    if not out_ngrams or not src_ngrams:
        return None
    containment = len(out_ngrams & src_ngrams) / max(1, len(out_ngrams))
    if containment < threshold:
        return f"grounding_low({containment:.2f}<{threshold})"
    return None


def check_dates_grounded(output: str, source_text: str) -> Optional[str]:
    """Reject when ``output`` states a calendar date absent from ``source_text``.

    Targets the hallucinated-date failure mode (e.g. a model writing "3月17日"
    into a story whose source never mentions it). Dates that genuinely appear
    in the source — including legitimate future-event dates — pass through,
    because grounding (not an absolute time window) is the criterion.
    """
    if not output or not source_text:
        return None
    out_dates = _chinese_dates(output)
    if not out_dates:
        return None
    src_dates = _chinese_dates(source_text) | _english_dates(source_text)
    ungrounded = out_dates - src_dates
    if ungrounded:
        month, day = sorted(ungrounded)[0]
        return f"ungrounded_date({month}月{day}日)"
    return None


def first_issue(*reasons: Optional[str]) -> Optional[str]:
    """Return the first non-empty reason, for terse call sites."""
    for r in reasons:
        if r:
            return r
    return None


def is_rejected_selection(status: Optional[str], *, blocked: Iterable[str] = ("rejected", "deferred")) -> bool:
    """Whether a content ``selection_status`` should be kept out of fallbacks."""
    return (status or "").strip().lower() in set(blocked)
