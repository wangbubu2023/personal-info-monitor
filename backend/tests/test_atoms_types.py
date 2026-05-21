"""Round-trip tests for atom Pydantic models."""

from app.domains.atoms.types import AtomCreate, DataAtomPayload, InfoAtomPayload, OpinionAtomPayload
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


def test_info_atom_example_from_schema_doc():
    payload = InfoAtomPayload(
        when="2026-05-18",
        where="深圳",
        who=[{"name": "华为", "type": SubjectType.COMPANY}],
        what_type=WhatType.PRODUCT,
        what="华为发布旗舰芯片麒麟X1",
        entities=["华为", "麒麟X1", "深圳"],
        validity=Validity.MEDIUM,
    )
    atom = AtomCreate(
        content_id="content-1",
        source_url="https://example.com/a",
        source_sentence="华为于2026年5月18日在深圳发布了全新旗舰芯片麒麟X1。",
        domain=Domain.TECH,
        atom_source="财新",
        source_credibility=0.95,
        fact_confidence=0.98,
        verified=True,
        atom_type=AtomType.INFO,
        payload=payload,
    )
    assert atom.payload.what == "华为发布旗舰芯片麒麟X1"


def test_opinion_atom_example_from_schema_doc():
    payload = OpinionAtomPayload(
        who=[{"name": "高盛首席经济学家", "type": SubjectType.PERSON}],
        role=Role.ANALYST,
        say_what="中国经济2026年全年增速有望达到5.2%",
        is_quote=False,
        context="研究报告",
        sentiment=Sentiment.POSITIVE,
        intensity=Intensity.CLEAR,
    )
    atom = AtomCreate(
        content_id="content-2",
        source_url="https://example.com/b",
        source_sentence="高盛首席经济学家表示，中国经济2026年全年增速有望达到5.2%。",
        domain=Domain.MACRO,
        atom_source="高盛",
        source_credibility=0.88,
        fact_confidence=0.75,
        atom_type=AtomType.OPINION,
        payload=payload,
    )
    assert atom.atom_type == AtomType.OPINION


def test_data_atom_example_from_schema_doc():
    payload = DataAtomPayload(
        source_org="比亚迪股份有限公司",
        source_type=DataSourceType.COMPANY_REPORT,
        metric="营收",
        value=1692,
        unit=Unit.CNY_100M,
        caliber="合并报表",
        period="2026Q1",
        period_type=PeriodType.QUARTER,
        is_relative=True,
        base_value=1244,
        base_period="2025Q1",
        validity=Validity.LONG,
    )
    atom = AtomCreate(
        content_id="content-3",
        source_url="https://example.com/c",
        source_sentence="比亚迪2026年Q1营收同比增长36%至1692亿元。",
        domain=Domain.AUTO,
        atom_source="比亚迪股份有限公司",
        source_credibility=0.99,
        fact_confidence=0.99,
        verified=True,
        atom_type=AtomType.DATA,
        payload=payload,
    )
    assert atom.payload.value == 1692
