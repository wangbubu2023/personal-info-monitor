"""Map atom_source names to default credibility scores."""

from __future__ import annotations

DEFAULT_SOURCE_CREDIBILITY: dict[str, float] = {
    "新华社": 0.97,
    "财新": 0.90,
    "彭博": 0.90,
    "Bloomberg": 0.90,
    "路透": 0.90,
    "Reuters": 0.90,
    "WSJ": 0.90,
    "华尔街日报": 0.90,
    "21世纪经济报道": 0.77,
    "第一财经": 0.77,
    "界面": 0.77,
    "国家统计局": 0.98,
    "中国人民银行": 0.98,
    "比亚迪股份有限公司": 0.99,
    "华为": 0.95,
    "高盛": 0.88,
    "匿名": 0.25,
}

_FALLBACK_CREDIBILITY = 0.55


def resolve_credibility(atom_source: str) -> float:
    name = (atom_source or "").strip()
    if not name:
        return _FALLBACK_CREDIBILITY
    if name in DEFAULT_SOURCE_CREDIBILITY:
        return DEFAULT_SOURCE_CREDIBILITY[name]
    lowered = name.lower()
    for key, score in DEFAULT_SOURCE_CREDIBILITY.items():
        if key.lower() in lowered or lowered in key.lower():
            return score
    return _FALLBACK_CREDIBILITY


__all__ = ["DEFAULT_SOURCE_CREDIBILITY", "resolve_credibility"]
