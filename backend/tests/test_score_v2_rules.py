"""Tests for pim-score-v2 rule dimensions."""

from __future__ import annotations

from types import SimpleNamespace

from app.domains.ingest.score_event import compute_corroboration, compute_event_score
from app.domains.ingest.score_rules import (
    classify_lane,
    compute_rule_dimension_scores,
    score_salience,
)
from app.domains.ingest.scoring import SCORE_VERSION, calculate_article_score, merge_rule_scoring_metadata


def test_lane_classifies_geopolitics_and_tech_independently():
    geo = classify_lane(
        "特朗普访华行程公布",
        "中美外交团队确认会晤安排。",
        "",
    )
    tech = classify_lane(
        "OpenAI releases new frontier model",
        "The new AI model improves reasoning benchmarks.",
        "",
    )
    assert geo == "geopolitics"
    assert tech == "tech_product"


def test_salience_balances_geo_and_tech_headlines():
    geo = score_salience(
        "特朗普访华",
        "中美举行高层会晤，讨论贸易与地区局势。",
        "",
    )
    tech = score_salience(
        "OpenAI releases GPT-5",
        "OpenAI announces a new model with major capability gains.",
        "",
    )
    assert geo >= 8.5
    assert tech >= 8.5


def test_corroboration_uses_source_id():
    items = [
        {"source_id": "s1", "source_name": "A", "metadata": {"source_stars": 3}},
        {"source_id": "s2", "source_name": "B", "metadata": {"source_stars": 2}},
        {"source_id": "s3", "source_name": "C", "metadata": {"source_stars": 2}},
    ]
    score, tier, count = compute_corroboration(items)
    assert tier == "strong"
    assert count == 3
    assert score == 9.0


def test_corroboration_single_high_star_source():
    items = [{"source_id": "s1", "source_name": "Official", "metadata": {"source_stars": 3}}]
    score, tier, _count = compute_corroboration(items)
    assert tier == "single_high"
    assert score == 5.5


def test_event_score_formula():
    items = [
        {
            "source_id": "s1",
            "metadata": {"final_score": 80, "source_stars": 3},
            "publish_time": None,
        },
        {
            "source_id": "s2",
            "metadata": {"final_score": 70, "source_stars": 2},
            "publish_time": None,
        },
    ]
    result = compute_event_score(items)
    assert result["event_score"] > 0
    assert result["independent_source_count"] == 2
    assert result["corroboration_tier"] == "moderate"


def test_merge_rule_scoring_metadata_stamps_v2():
    content = SimpleNamespace(content_type="website", metadata_={})
    meta = merge_rule_scoring_metadata(
        {"fulltext_status": "full", "content_quality": 0.9},
        title="OpenAI releases new model",
        summary="OpenAI announced a new frontier model with improved capabilities.",
        full_content="OpenAI announced a new frontier model. " * 50,
        source_metadata={"source_stars": 3, "authority_type": "primary"},
        content_type="website",
        content=content,
    )
    assert meta["score_version"] == SCORE_VERSION
    assert meta["scoring_method"] == "rule"
    assert meta["lane"] == "tech_product"
    assert "salience" in meta["dimension_scores"]
    assert meta["subjective_meta"]["source"] == "fixed_baseline"
    assert meta["dimension_scores"]["subjective"] == 5.0
    assert meta["article_score"] == meta["final_score"]


def test_calculate_article_score_selected_threshold():
    result = calculate_article_score(
        {
            "salience": 9.0,
            "reach": 9.0,
            "authority": 8.5,
            "depth": 7.0,
            "subjective": 5.0,
        },
        content_metadata={"fulltext_status": "full", "content_quality": 0.9},
        source_metadata={"source_stars": 3},
        lane="tech_product",
    )
    # New weights: (0.30*9+0.25*9+0.25*8.5+0.20*7)*10 = (2.7+2.25+2.125+1.4)*10 = 84.75
    assert result["selection_status"] == "selected"
    assert result["article_score"] >= 60


def test_vocab_recognizes_major_entities():
    from app.domains.ingest.score_vocab_runtime import RuntimeScoringVocab

    vocab = RuntimeScoringVocab.build()
    assert vocab.entity_tier_score("鲍威尔在杰克逊霍尔发表演讲") == 9.0
    assert vocab.entity_tier_score("deepseek 发布新模型") == 7.5
    assert vocab.entity_tier_score("红杉领投 A 轮") == 6.0


def test_user_keywords_merge_into_runtime_vocab():
    from app.domains.ingest.score_vocab_runtime import RuntimeScoringVocab

    vocab = RuntimeScoringVocab.build(
        user_keyword_terms=("MyPrivateCo",),
        matched_user_terms=("MyPrivateCo",),
    )
    assert "MyPrivateCo" in vocab.entity_tier_b
    salience = score_salience(
        "MyPrivateCo raises funding",
        "The company announced a new round.",
        "",
        runtime_vocab=vocab,
    )
    assert salience >= 7.5


def test_merge_rule_scoring_metadata_includes_user_vocab_fields():
    content = SimpleNamespace(content_type="website", metadata_={})

    class FakeKeyword:
        enabled = True
        keyword = "AcmeCorp"
        equivalent_terms = ["Acme Corp"]

    meta = merge_rule_scoring_metadata(
        {"fulltext_status": "full", "content_quality": 0.9, "fetch_acceptance": "accepted"},
        title="AcmeCorp launches product",
        summary="Acme Corp announced a major product launch today with details.",
        full_content="Acme Corp announced a major product launch today. " * 30,
        source_metadata={"source_stars": 2},
        content_type="website",
        content=content,
        keyword_objects=[FakeKeyword()],
        keyword_matches=[{"keyword": "AcmeCorp", "matched_term": "AcmeCorp"}],
    )
    assert "AcmeCorp" in meta["score_vocab_user_terms"]
    assert "AcmeCorp" in meta["score_vocab_matched_user_terms"]
    assert meta["dimension_scores"]["salience"] >= 7.5


def test_deal_and_product_scoped_articles_score_lower():
    """Promo / accessory / division-hire stories should not rank as selected."""
    anker_title = "安克公司推出的适合旅行的笔记本电脑电源适配器，以今年最优惠的价格回归市场。"
    anker_summary = (
        "Anker的笔记本电脑电源适配器在亚马逊有售，价格为95.99美元（优惠24美元），"
        "这是今年我们看到的最优惠价格。"
    )
    xbox_title = "微软聘请了一位在视频游戏领域有影响力的博主来修复Xbox的问题。"
    xbox_summary = (
        "Xbox已经聘请了Matthew Ball担任首席战略官，以加强其机顶设备业务。"
        "该业务由于全球内存短缺而陷入困境。"
    )
    content = SimpleNamespace(content_type="website", metadata_={})
    meta = {"fulltext_status": "full", "content_quality": 0.9, "fetch_acceptance": "accepted"}

    anker_lane, anker_dims, _ = compute_rule_dimension_scores(
        title=anker_title,
        summary=anker_summary,
        full_content=anker_summary * 20,
        content_metadata=meta,
        source_metadata={"source_stars": 2},
        content_type="website",
        content=content,
    )
    xbox_lane, xbox_dims, _ = compute_rule_dimension_scores(
        title=xbox_title,
        summary=xbox_summary,
        full_content=xbox_summary * 20,
        content_metadata=meta,
        source_metadata={"source_stars": 2},
        content_type="website",
        content=content,
    )
    anker_score = calculate_article_score(
        anker_dims, content_metadata=meta, source_metadata={"source_stars": 2}, lane=anker_lane
    )["article_score"]
    xbox_score = calculate_article_score(
        xbox_dims, content_metadata=meta, source_metadata={"source_stars": 2}, lane=xbox_lane
    )["article_score"]

    assert anker_dims["salience"] <= 4.0
    assert anker_dims["reach"] <= 3.5
    assert anker_dims["depth"] <= 4.5
    assert anker_score < 48
    assert xbox_dims["salience"] <= 7.0
    assert xbox_dims["reach"] <= 5.5
    assert xbox_score < 70


def test_commerce_promo_and_subscription_features_score_very_low():
    content = SimpleNamespace(content_type="website", metadata_={})
    meta = {"fulltext_status": "full", "content_quality": 0.9, "fetch_acceptance": "accepted"}
    cases = [
        "Hulu套餐的订阅用户现在可以在Disney+应用程序中查看他们的观看记录和推荐内容。",
        "以下是REI大型周年促销活动中我们最喜欢的42个优惠活动。",
        "一款功能丰富的MagSafe充电宝在阵亡将士纪念日当天有20%的折扣优惠。",
        "安克公司推出的适合旅行的笔记本电脑电源适配器，以今年最优惠的价格回归市场。",
    ]
    for title in cases:
        lane, dims, _ = compute_rule_dimension_scores(
            title=title,
            summary=f"{title} " * 5,
            full_content=(title + " ") * 40,
            content_metadata=meta,
            source_metadata={"source_stars": 2},
            content_type="website",
            content=content,
        )
        score = calculate_article_score(
            dims, content_metadata=meta, source_metadata={"source_stars": 2}, lane=lane
        )["article_score"]
        assert dims["salience"] <= 4.0, title
        assert dims["reach"] <= 3.5, title
        assert dims["depth"] <= 4.5, title
        assert score < 48, title


def test_anthropic_openai_politics_not_commerce_capped():
    from app.domains.ingest.summary_clean import clean_listing_summary

    content = SimpleNamespace(content_type="website", metadata_={})
    meta = {"fulltext_status": "full", "content_quality": 0.9, "fetch_acceptance": "accepted"}
    title = "人类主义和OpenAI将他们的分歧带入了中期选举"
    raw_summary = (
        "您好，欢迎来到《Regulator》！这是一份为Verge订阅者准备的通讯。"
        "如果您还不是订阅用户，请立即注册我们的优质编辑刊物。"
        "Anthropic 与 OpenAI 的超级 PAC 角力正在影响中期选举。"
    )
    summary = clean_listing_summary(raw_summary) or "Anthropic 与 OpenAI 的超级 PAC 角力正在影响中期选举。"
    lane, dims, _ = compute_rule_dimension_scores(
        title=title,
        summary=summary,
        full_content=(summary + " ") * 30,
        content_metadata=meta,
        source_metadata={"source_stars": 2},
        content_type="website",
        content=content,
    )
    score = calculate_article_score(
        dims, content_metadata=meta, source_metadata={"source_stars": 2}, lane=lane
    )["article_score"]
    assert dims["salience"] >= 8.5
    assert dims["reach"] >= 5.5
    assert score >= 59


def test_ipo_headline_not_capped_as_commerce_deal():
    content = SimpleNamespace(content_type="website", metadata_={})
    meta = {"fulltext_status": "full", "content_quality": 0.9, "fetch_acceptance": "accepted"}
    title = "SpaceX files for stock sale that could make Musk a trillionaire"
    summary = (
        "SpaceX filed for an IPO on Wednesday, disclosing financials for the first time. "
        "Elon Musk could become the world's first trillionaire after the offering."
    )
    lane, dims, _ = compute_rule_dimension_scores(
        title=title,
        summary=summary,
        full_content=summary * 30,
        content_metadata=meta,
        source_metadata={"source_stars": 2},
        content_type="website",
        content=content,
    )
    score = calculate_article_score(
        dims, content_metadata=meta, source_metadata={"source_stars": 2}, lane=lane
    )["article_score"]
    assert dims["salience"] >= 8.5
    assert dims["reach"] >= 7.0
    assert score >= 68


def test_disaster_casualty_headline_scores_higher():
    content = SimpleNamespace(content_type="website", metadata_={})
    meta = {"fulltext_status": "partial", "content_quality": 0.8, "fetch_acceptance": "accepted"}
    title = "中国多地遭遇强降雨和山洪暴发，已致至少22人死亡"
    summary = (
        "强降雨导致中国西南部多个城镇发生洪灾。广西一辆车辆坠河造成10人死亡，"
        "贵州有四人死亡、五人失联，湖北有三人死亡、四人失联。"
    )
    lane, dims, _ = compute_rule_dimension_scores(
        title=title,
        summary=summary,
        full_content=(summary + "\n\n") * 8,
        content_metadata=meta,
        source_metadata={"source_stars": 2},
        content_type="website",
        content=content,
    )
    score = calculate_article_score(
        dims, content_metadata=meta, source_metadata={"source_stars": 2}, lane=lane
    )["article_score"]
    assert lane == "geopolitics"
    assert dims["salience"] >= 9.0
    assert dims["reach"] >= 9.0
    assert dims["depth"] >= 3.0
    assert score >= 68


def test_vocab_lane_terms_macro_and_regulation():
    macro = classify_lane("美联储维持利率不变", "FOMC 声明暗示年内仍可能降息。", "")
    reg = classify_lane("网信办发布生成式 AI 管理办法", "征求意见稿向社会公开。", "")
    assert macro == "macro_finance"
    assert reg == "regulation"


def test_recommendation_reason_excludes_subjective_from_high_dimensions():
    from app.domains.score.scoring import build_recommendation_reason
    reason = build_recommendation_reason(
        {"salience": 9.0, "reach": 7.0, "authority": 8.5, "depth": 6.0, "subjective": 5.0},
        final_score=80.0,
        selection_status="selected",
        source_stars=3,
        score_confidence=0.85,
    )
    assert "主观判断" not in reason["why_matters"]


def test_confidence_limited_flag_for_title_only():
    result = calculate_article_score(
        {"salience": 9.0, "reach": 9.0, "authority": 8.5, "depth": 4.0, "subjective": 5.0},
        content_metadata={"fulltext_status": "title_only", "content_quality": 0.5},
        source_metadata={"source_stars": 3},
    )
    # title_only evidence_confidence=0.22; confidence will be low, blocking selection
    assert result["confidence_limited_by_fulltext"] is True
    assert result["selection_status"] == "candidate"


def test_confidence_limited_flag_false_for_full_content():
    result = calculate_article_score(
        {"salience": 9.0, "reach": 9.0, "authority": 8.5, "depth": 7.0, "subjective": 5.0},
        content_metadata={"fulltext_status": "full", "content_quality": 0.9},
        source_metadata={"source_stars": 3},
    )
    assert result["confidence_limited_by_fulltext"] is False
    assert result["selection_status"] == "selected"


def test_reach_major_entity_for_s_tier_without_sector_keyword():
    from app.domains.score.score_rules import score_reach
    from app.domains.score.score_vocab_runtime import RuntimeScoringVocab

    vocab = RuntimeScoringVocab.build()
    # OpenAI is S-tier, no sector keyword in title
    reach = score_reach("OpenAI announces quarterly update", None, None, runtime_vocab=vocab)
    assert reach == 6.5  # major_entity


def test_reach_sector_keyword_takes_precedence_over_major_entity():
    from app.domains.score.score_rules import score_reach
    from app.domains.score.score_vocab_runtime import RuntimeScoringVocab

    vocab = RuntimeScoringVocab.build()
    # "ecosystem" is a sector keyword in REACH_KEYWORDS["sector"]
    reach = score_reach("OpenAI transforms the AI ecosystem broadly", None, None, runtime_vocab=vocab)
    assert reach == 7.0  # sector keyword takes precedence


def test_reach_entity_without_runtime_vocab():
    from app.domains.score.score_rules import score_reach
    # Without runtime_vocab, S-tier entities don't get the boost
    reach = score_reach("OpenAI announces quarterly update", None, None)
    assert reach == 5.5  # plain entity (no vocab = no boost)


def test_reach_entity_for_non_s_tier():
    from app.domains.score.score_rules import score_reach
    from app.domains.score.score_vocab_runtime import RuntimeScoringVocab

    vocab = RuntimeScoringVocab.build()
    reach = score_reach("Acme startup announces product update", None, None, runtime_vocab=vocab)
    assert reach == 5.5  # plain entity
