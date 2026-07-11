"""Tests for single-user feedback observation helpers."""

from __future__ import annotations

from types import SimpleNamespace

from app.domains.score.personalization import (
    PersonalPreferenceProfile,
    ScopeSignal,
    apply_personal_preference_adjustment,
    describe_personal_preference_observations,
)


def test_personal_preference_observations_do_not_change_scores():
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
    assert personalized["final_score"] == 62.0
    assert personalized["selection_status"] == "candidate"
    assert "personalization" not in personalized
    assert "personalization_adjustment" not in personalized["recommendation_reason"]
    assert personalized["personal_observation"]["effect"] == "observation_only"
    assert personalized["personal_observation"]["signals_considered"] == 3


def test_negative_personal_preference_observations_do_not_demote_selected_item():
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
    assert personalized["final_score"] == 72.0
    assert personalized["selection_status"] == "selected"
    assert personalized["personal_observation"]["effect"] == "observation_only"
    assert "personalization" not in personalized


def test_personal_preference_observation_keeps_high_signal_as_observation():
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

    assert personalized["final_score"] == 50.0
    assert personalized["personal_observation"]["effect"] == "observation_only"
    assert personalized["personal_observation"]["observations"][0]["adjustment"] == 6.0


def test_describe_personal_preference_observations_returns_none_without_matching_scope():
    profile = PersonalPreferenceProfile(
        source={"other-source": ScopeSignal(score=3.0, count=1)},
        total_signals=1,
    )
    content = SimpleNamespace(source_id="source-1", content_type="website")

    assert describe_personal_preference_observations(profile, content=content, metadata={}) is None
