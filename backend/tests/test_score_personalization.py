"""Tests for single-user score personalization."""

from __future__ import annotations

from types import SimpleNamespace

from app.domains.score.personalization import (
    PersonalPreferenceProfile,
    ScopeSignal,
    apply_personal_preference_adjustment,
)


def test_personal_preference_raises_final_score_without_changing_article_score():
    profile = PersonalPreferenceProfile(
        source={"source-1": ScopeSignal(score=3.2, count=2)},
        lane={"tech_product": ScopeSignal(score=1.4, count=1)},
        content_type={"website": ScopeSignal(score=0.5, count=1)},
        total_signals=3,
    )
    content = SimpleNamespace(source_id="source-1", content_type="website")
    meta = {
        "article_score": 62.0,
        "final_score": 62.0,
        "score_confidence": 0.9,
        "lane": "tech_product",
        "selection_status": "candidate",
        "recommendation_reason": {"why_matters": "base"},
    }

    personalized = apply_personal_preference_adjustment(meta, profile, content=content)

    assert personalized["article_score"] == 62.0
    assert personalized["final_score"] == 67.1
    assert personalized["selection_status"] == "candidate"
    assert personalized["personalization"]["adjustment"] == 5.1
    assert personalized["recommendation_reason"]["personalization_adjustment"] == 5.1


def test_personal_preference_can_lower_selected_item_to_candidate():
    profile = PersonalPreferenceProfile(
        source={"source-1": ScopeSignal(score=-5.0, count=2)},
        lane={"geopolitics": ScopeSignal(score=-2.0, count=1)},
        content_type={},
        total_signals=3,
    )
    content = SimpleNamespace(source_id="source-1", content_type="website")
    meta = {
        "article_score": 72.0,
        "final_score": 72.0,
        "score_confidence": 0.9,
        "lane": "geopolitics",
        "selection_status": "selected",
    }

    personalized = apply_personal_preference_adjustment(meta, profile, content=content)

    assert personalized["article_score"] == 72.0
    assert personalized["final_score"] == 65.0
    assert personalized["selection_status"] == "candidate"
    assert personalized["personalization"]["base_score"] == 72.0


def test_personal_preference_caps_total_adjustment():
    profile = PersonalPreferenceProfile(
        source={"source-1": ScopeSignal(score=20.0, count=10)},
        lane={"tech_product": ScopeSignal(score=20.0, count=10)},
        content_type={"website": ScopeSignal(score=20.0, count=10)},
        total_signals=30,
    )
    content = SimpleNamespace(source_id="source-1", content_type="website")
    meta = {
        "article_score": 50.0,
        "final_score": 50.0,
        "score_confidence": 0.9,
        "lane": "tech_product",
    }

    personalized = apply_personal_preference_adjustment(meta, profile, content=content)

    assert personalized["final_score"] == 58.0
    assert personalized["personalization"]["adjustment"] == 8.0
