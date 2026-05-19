from app.services.content_quality_service import (
    FULLTEXT_STATUS_BLOCKED,
    FULLTEXT_STATUS_FULL,
    FULLTEXT_STATUS_SUMMARY_ONLY,
    assess_content_quality,
    merge_content_quality_metadata,
)
from app.services.scoring_service import (
    calculate_final_score,
    compute_domain_match,
    merge_baseline_scoring_metadata,
)


def test_content_quality_marks_long_body_as_full():
    body = "\n\n".join(
        [
            "This is a substantial paragraph about a model release with concrete details. " * 6,
            "This paragraph adds implementation details and enough evidence for scoring. " * 6,
            "This final paragraph contains impact and rollout information for readers. " * 6,
        ]
    )

    quality = assess_content_quality(title="Model release", full_content=body, summary="")

    assert quality.fulltext_status == FULLTEXT_STATUS_FULL
    assert quality.score_basis == "full_content"
    assert quality.content_quality >= 0.78


def test_content_quality_marks_summary_only_without_guessing_fulltext():
    quality = assess_content_quality(
        title="Short RSS item",
        full_content="",
        summary="This RSS description is enough for rough prefiltering but not a full article.",
    )

    assert quality.fulltext_status == FULLTEXT_STATUS_SUMMARY_ONLY
    assert quality.score_basis == "summary"
    assert 0 < quality.content_quality < 0.5


def test_content_quality_marks_cookie_required_unobtained_as_blocked():
    meta = merge_content_quality_metadata(
        {"cookie_fulltext_required": True, "cookie_fulltext_obtained": False},
        title="Paywalled article",
        full_content="",
        summary="",
    )

    assert meta["fulltext_status"] == FULLTEXT_STATUS_BLOCKED
    assert meta["score_basis"] == "blocked"
    assert meta["content_quality"] == 0.0


def test_scoring_selects_high_quality_matching_source():
    result = calculate_final_score(
        {
            "topic_relevance": 9,
            "novelty": 8,
            "impact": 8,
            "authority": 9,
            "actionability": 8,
            "risk": 2,
        },
        content_metadata={"fulltext_status": "full", "content_quality": 0.9, "domain_match": 1.0},
        source_metadata={"source_stars": 3, "source_weight": 1.1},
    )

    assert result["selection_status"] == "selected"
    assert result["final_score"] >= 75
    assert result["score_confidence"] >= 0.65


def test_scoring_penalizes_domain_mismatch_even_for_high_star_source():
    matched = calculate_final_score(
        {"topic_relevance": 8, "novelty": 7, "impact": 7, "authority": 8, "actionability": 7, "risk": 1},
        content_metadata={"fulltext_status": "full", "content_quality": 0.9, "domain_match": 1.0},
        source_metadata={"source_stars": 3},
    )
    mismatched = calculate_final_score(
        {"topic_relevance": 8, "novelty": 7, "impact": 7, "authority": 8, "actionability": 7, "risk": 1},
        content_metadata={"fulltext_status": "full", "content_quality": 0.9, "domain_match": 0.25},
        source_metadata={"source_stars": 3},
    )

    assert matched["final_score"] > mismatched["final_score"]
    assert mismatched["domain_match"] == 0.25


def test_blocked_high_star_content_is_deferred_not_selected():
    result = calculate_final_score(
        {"topic_relevance": 10, "novelty": 10, "impact": 10, "authority": 10, "actionability": 10, "risk": 0},
        content_metadata={"fulltext_status": "blocked", "content_quality": 0.0},
        source_metadata={"source_stars": 3},
    )

    assert result["selection_status"] == "deferred"
    assert result["final_score"] < 75
    assert result["score_confidence"] == 0.0


def test_compute_domain_match_defaults_to_no_penalty_without_focus():
    assert compute_domain_match({}, "anything") == 1.0
    assert compute_domain_match({"domain_focus": ["semiconductor"]}, "new AI model launch") == 0.25
    assert compute_domain_match({"domain_focus": ["AI", "model"]}, "new AI model launch") > 0.7


def test_baseline_scoring_stamps_final_score_without_model_dimensions():
    meta = merge_baseline_scoring_metadata(
        {"fulltext_status": "full", "content_quality": 0.9},
        title="OpenAI releases new model",
        summary="The new AI model improves developer workflows.",
        full_content="The new AI model improves developer workflows. " * 80,
        source_metadata={"source_stars": 3, "domain_focus": ["AI", "model"], "source_weight": 1.1},
    )

    assert meta["scoring_method"] == "baseline"
    assert meta["score_version"] == "pim-score-v1"
    assert meta["domain_match"] > 0.7
    assert meta["final_score"] > 0
    assert meta["selection_status"] in {"selected", "candidate", "rejected"}
    assert meta["recommendation_reason"]["why_matters"]
    assert meta["recommendation_reason"]["source_context"].startswith("来自3星信源")
    assert meta["recommendation_reason"]["reason_source"] == "baseline"


def test_baseline_scoring_preserves_existing_model_dimensions():
    original = {
        "score_version": "model-score-v1",
        "dimension_scores": {"topic_relevance": 10},
        "final_score": 91,
    }

    meta = merge_baseline_scoring_metadata(
        original,
        title="Anything",
        source_metadata={"source_stars": 1},
    )

    assert meta == original
