from app.domains.ingest.quality_metadata import (
    FULLTEXT_STATUS_BLOCKED,
    FULLTEXT_STATUS_FULL,
    FULLTEXT_STATUS_SUMMARY_ONLY,
    assess_content_quality,
    merge_content_quality_metadata,
)
from app.domains.score.scoring import (
    SCORE_VERSION,
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
            "salience": 9,
            "reach": 9,
            "authority": 9,
            "depth": 8,
            "subjective": 5,
        },
        content_metadata={"fulltext_status": "full", "content_quality": 0.9},
        source_metadata={"source_stars": 3},
        lane="product_news",
    )

    assert result["selection_status"] == "selected"
    assert result["article_score"] >= 75
    assert result["score_confidence"] >= 0.65


def test_scoring_v2_no_domain_penalty():
    high = calculate_final_score(
        {"salience": 8, "reach": 8, "authority": 8, "depth": 7, "subjective": 5},
        content_metadata={"fulltext_status": "full", "content_quality": 0.9},
        source_metadata={"source_stars": 3},
        lane="product_news",
    )
    assert high["article_score"] >= 70


def test_blocked_content_legacy_metadata_still_scores():
    result = calculate_final_score(
        {"salience": 10, "reach": 10, "authority": 10, "depth": 10, "subjective": 5},
        content_metadata={"fulltext_status": "blocked", "content_quality": 0.0},
        source_metadata={"source_stars": 3},
    )

    assert result["selection_status"] in {"selected", "candidate", "rejected"}
    assert result["article_score"] >= 0


def test_compute_domain_match_defaults_to_no_penalty_without_focus():
    assert compute_domain_match({}, "anything") == 1.0
    assert compute_domain_match({"domain_focus": ["semiconductor"]}, "new AI model launch") == 0.25
    assert compute_domain_match({"domain_focus": ["AI", "model"]}, "new AI model launch") > 0.7


def test_rule_scoring_stamps_final_score():
    meta = merge_baseline_scoring_metadata(
        {"fulltext_status": "full", "content_quality": 0.9, "fetch_acceptance": "accepted"},
        title="OpenAI releases new model",
        summary="The new AI model improves developer workflows.",
        full_content="The new AI model improves developer workflows. " * 80,
        source_metadata={"source_stars": 3, "authority_type": "primary"},
        content_type="website",
    )

    assert meta["scoring_method"] == "rule"
    assert meta["score_version"] == SCORE_VERSION
    assert meta["lane"] == "product_news"
    assert meta["final_score"] > 0
    assert meta["selection_status"] in {"selected", "candidate", "rejected"}
    assert meta["recommendation_reason"]["why_matters"]
    assert meta["recommendation_reason"]["reason_source"] == "rule"


def test_rule_scoring_preserves_existing_v2_dimensions():
    original = {
        "score_version": SCORE_VERSION,
        "dimension_scores": {"salience": 10},
        "final_score": 91,
    }

    meta = merge_baseline_scoring_metadata(
        original,
        title="Anything",
        source_metadata={"source_stars": 1},
    )

    assert meta == original
