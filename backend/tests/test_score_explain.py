"""Tests for score explain helpers."""

from __future__ import annotations

from app.domains.score.score_explain import explain_content_score


def test_explain_includes_weight_breakdown_and_caps():
    meta = {"fulltext_status": "full", "content_quality": 0.9, "fetch_acceptance": "accepted"}
    payload = explain_content_score(
        title="安克公司推出的适合旅行的笔记本电脑电源适配器，以今年最优惠的价格回归市场。",
        summary="Anker的笔记本电脑电源适配器在亚马逊有售，价格为95.99美元（优惠24美元）。",
        full_content="Anker deal " * 40,
        content_metadata=meta,
        source_metadata={"source_stars": 2},
        content_type="website",
        stored_metadata={"article_score": 77.0, "selection_status": "selected"},
    )

    assert payload["impact_cap_scope"] == "commerce"
    assert payload["recomputed"]["article_score"] < 60
    assert payload["score_delta"] is not None
    assert len(payload["weight_breakdown"]) == 5
    assert payload["weighted_sum_0_10"] > 0
    assert payload["matched_signals"]["commerce"]


def test_explain_geo_headline_scores_high():
    meta = {"fulltext_status": "full", "content_quality": 0.9, "fetch_acceptance": "accepted"}
    payload = explain_content_score(
        title="特朗普访华行程公布",
        summary="中美外交团队确认会晤安排，讨论贸易与地区局势。",
        full_content="",
        content_metadata=meta,
        source_metadata={"source_stars": 3, "authority_type": "primary"},
        content_type="website",
    )
    assert payload["lane"] == "geopolitics"
    assert payload["recomputed"]["article_score"] >= 60
    assert payload["dimension_scores"]["salience"] >= 8.0
