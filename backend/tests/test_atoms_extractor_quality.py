"""Tests for the post-extraction atom quality gate."""

from __future__ import annotations

from app.domains.atoms.extractor.quality import (
    dedupe_by_source_sentence,
    filter_atoms,
    reject_atom_reason,
)
from app.domains.atoms.types import AtomCreate, payload_from_dict
from app.domains.atoms.vocab import AtomType, Domain


def _info_atom(sentence: str, *, confidence: float = 0.9) -> AtomCreate:
    return AtomCreate(
        content_id="c1",
        source_url="https://example.com/a",
        source_sentence=sentence,
        domain=Domain.TECH,
        atom_source="财新",
        source_credibility=0.8,
        fact_confidence=confidence,
        verified=False,
        atom_type=AtomType.INFO,
        payload=payload_from_dict(
            AtomType.INFO,
            {
                "who": [{"name": "华为", "type": "企业"}],
                "what_type": "产品",
                "what": "华为发布旗舰芯片麒麟X1",
                "entities": ["华为", "麒麟X1"],
                "validity": "中期",
            },
        ),
    )


def _opinion_atom(sentence: str, *, confidence: float = 0.9) -> AtomCreate:
    return AtomCreate(
        content_id="c1",
        source_url="https://example.com/a",
        source_sentence=sentence,
        domain=Domain.TECH,
        atom_source="某分析师",
        source_credibility=0.6,
        fact_confidence=confidence,
        verified=False,
        atom_type=AtomType.OPINION,
        payload=payload_from_dict(
            AtomType.OPINION,
            {
                "who": [{"name": "某分析师", "type": "人物"}],
                "role": "分析师",
                "say_what": "该公司估值偏高",
                "is_quote": False,
                "sentiment": "负面",
                "intensity": "明确",
            },
        ),
    )


def _data_atom(
    sentence: str,
    *,
    metric: str = "营收",
    unit: str = "%（百分比）",
    period: str = "2026Q1",
    caliber: str | None = None,
    confidence: float = 0.9,
) -> AtomCreate:
    return AtomCreate(
        content_id="c1",
        source_url="https://example.com/a",
        source_sentence=sentence,
        domain=Domain.FINANCE,
        atom_source="某机构",
        source_credibility=0.8,
        fact_confidence=confidence,
        verified=False,
        atom_type=AtomType.DATA,
        payload=payload_from_dict(
            AtomType.DATA,
            {
                "source_org": "某机构",
                "source_type": "二手/研究机构",
                "metric": metric,
                "value": 9.2,
                "unit": unit,
                "caliber": caliber,
                "period": period,
                "period_type": "季度",
                "is_relative": False,
                "validity": "短期",
            },
        ),
    )


def test_title_duplicate_rejected():
    atom = _info_atom("华为发布旗舰芯片麒麟X1，面向高端智能手机市场需求增长。")
    reason = reject_atom_reason(atom, title="华为发布旗舰芯片麒麟X1，面向高端智能手机市场需求增长。", source_text="...")
    assert reason == "title_duplicate"


def test_low_confidence_info_rejected():
    atom = _info_atom("华为发布旗舰芯片麒麟X1，面向高端智能手机市场需求增长。", confidence=0.5)
    assert reject_atom_reason(atom, title="t", source_text="...") == "low_confidence"


def test_opinion_lower_confidence_floor():
    atom = _opinion_atom("该公司估值偏高，市场情绪明显趋于谨慎并持续走弱。", confidence=0.65)
    assert reject_atom_reason(atom, title="t", source_text="...") is None


def test_data_missing_period_rejected():
    atom = _data_atom("某指标同比增长9.2%，反映行业景气度持续回升态势。", period="未知")
    assert reject_atom_reason(atom, title="t", source_text="...") == "data_missing_period"


def test_data_custom_unit_without_caliber_rejected():
    atom = _data_atom("某指标录得9.2，整体高于市场此前的一致预期水平。", unit="自定义", caliber=None)
    assert reject_atom_reason(atom, title="t", source_text="...") == "data_custom_unit_without_caliber"


def test_data_no_numeric_evidence_rejected():
    atom = _data_atom("该机构发布了最新的行业研究结论与展望分析报告内容。")
    assert reject_atom_reason(atom, title="t", source_text="...") == "data_no_numeric_evidence"


def test_data_suspicious_metric_rejected():
    atom = _data_atom("某关键词在文中出现9次，被反复强调以突出其重要性。", metric="occurrence_count")
    assert reject_atom_reason(atom, title="t", source_text="...") == "data_suspicious_metric"


def test_dedupe_keeps_highest_priority_type():
    sentence = "某机构发布数据显示某指标同比增长9.2%，市场普遍认为偏高。"
    info = _info_atom(sentence)
    data = _data_atom(sentence)
    deduped = dedupe_by_source_sentence([info, data])
    assert len(deduped) == 1
    assert deduped[0].atom_type == AtomType.DATA


def test_filter_atoms_reports_stats():
    good = _info_atom("华为于2026年发布了旗舰芯片麒麟X1，加速布局高端智能手机市场。")
    bad = _info_atom("华为发布。", confidence=0.9)
    kept, stats = filter_atoms([good, bad], title="标题", source_text="...")
    assert len(kept) == 1
    assert stats.get("short_cjk") == 1
