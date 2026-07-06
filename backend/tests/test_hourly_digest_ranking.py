from pathlib import Path

from app.domains.score.ranking import RankingService


def test_ranking_prefers_multi_source_clusters():
    service = RankingService(similarity_threshold=0.2)
    entries = [
        {
            "title": "US announces new AI chip export restrictions",
            "summary": "Policy update affects semiconductor supply chain and cloud providers.",
            "source_name": "SourceA",
            "source_url": "https://a.example.com",
            "article_url": "https://a.example.com/ai-chip-policy",
        },
        {
            "title": "AI chip export policy tightened by US government",
            "summary": "Several regions and companies face expanded restrictions.",
            "source_name": "SourceB",
            "source_url": "https://b.example.com",
            "article_url": "https://b.example.com/us-export-policy",
        },
        {
            "title": "Local startup raises series A",
            "summary": "Funding round details.",
            "source_name": "SourceC",
            "source_url": "https://c.example.com",
            "article_url": "https://c.example.com/startup-series-a",
        },
    ]

    clusters = service.cluster_and_rank(entries)

    assert len(clusters) >= 2
    assert len(clusters[0]["sources"]) == 2


def test_ranking_can_exclude_previous_event_keys():
    service = RankingService(similarity_threshold=0.2)
    entries = [
        {
            "title": "Major central bank keeps rates unchanged",
            "summary": "Decision and press conference highlights.",
            "source_name": "SourceA",
            "source_url": "https://a.example.com",
            "article_url": "https://a.example.com/rates",
        },
        {
            "title": "Central bank leaves interest rates steady",
            "summary": "Market reaction remains mixed.",
            "source_name": "SourceB",
            "source_url": "https://b.example.com",
            "article_url": "https://b.example.com/rates-steady",
        },
    ]

    baseline = service.cluster_and_rank(entries)
    assert baseline

    excluded = {cluster["event_key"] for cluster in baseline}
    filtered = service.cluster_and_rank(entries, excluded_event_keys=excluded)
    assert filtered == []


def test_ranking_prefers_scored_high_quality_entries_over_long_low_quality_items():
    service = RankingService(similarity_threshold=0.2)
    entries = [
        {
            "title": "Routine newsletter roundup with many minor links",
            "summary": "Minor update. " * 240,
            "source_name": "Aggregator",
            "source_url": "https://agg.example.com",
            "article_url": "https://agg.example.com/roundup",
            "metadata": {
                "final_score": 28,
                "source_stars": 1,
                "selection_status": "rejected",
                "fulltext_status": "summary_only",
                "score_confidence": 0.5,
            },
        },
        {
            "title": "OpenAI releases major model safety report",
            "summary": "Official report details model capability, safety mitigations, and deployment constraints.",
            "source_name": "Official",
            "source_url": "https://openai.com",
            "article_url": "https://openai.com/report",
            "metadata": {
                "final_score": 88,
                "source_stars": 3,
                "selection_status": "selected",
                "fulltext_status": "full",
                "score_confidence": 0.9,
            },
        },
    ]

    clusters = service.cluster_and_rank(entries)

    assert clusters[0]["topic"] == "OpenAI releases major model safety report"


def test_ranking_clusters_high_score_entries_first_for_stable_topic():
    service = RankingService(similarity_threshold=0.2)
    entries = [
        {
            "title": "Brief AI policy note",
            "summary": "AI policy update from a wire.",
            "source_name": "Wire",
            "source_url": "https://wire.example.com",
            "metadata": {"article_score": 35},
        },
        {
            "title": "White House announces major AI chip export policy",
            "summary": "AI chip export policy update with semiconductor supply chain impact.",
            "source_name": "Primary",
            "source_url": "https://primary.example.com",
            "metadata": {"article_score": 92},
        },
    ]

    clusters = service.cluster_and_rank(entries)

    assert clusters[0]["topic"] == "White House announces major AI chip export policy"
    assert clusters[0]["items"][0]["source_name"] == "Primary"


def test_ranking_forces_duplicate_group_into_same_cluster():
    service = RankingService(similarity_threshold=0.9)
    entries = [
        {
            "title": "Central bank publishes policy framework",
            "summary": "Monetary policy and market impact.",
            "source_name": "A",
            "source_url": "https://a.example.com",
            "metadata": {"article_score": 80, "duplicate_group_id": "policy-framework"},
        },
        {
            "title": "Unrelated wire headline text",
            "summary": "A syndicated rewrite with sparse overlapping tokens.",
            "source_name": "B",
            "source_url": "https://b.example.com",
            "metadata": {"article_score": 50, "duplicate_group_id": "policy-framework"},
        },
    ]

    clusters = service.cluster_and_rank(entries)

    assert len(clusters) == 1
    assert len(clusters[0]["items"]) == 2


def test_tokenize_includes_chinese_trigrams():
    from app.domains.score.ranking import _tokenize

    tokens = _tokenize("中国人民银行宣布降息")
    # bigrams
    assert "人民" in tokens
    assert "银行" in tokens
    # trigrams
    assert "人民银" in tokens
    assert "民银行" in tokens


def test_tokenize_trigram_improves_similarity():
    from app.domains.score.ranking import _jaccard, _tokenize

    a = _tokenize("中国人民银行宣布利率决定")
    b = _tokenize("人民银行维持基准利率不变")
    score = _jaccard(a, b)
    assert score > 0.15  # trigrams give overlap on "人民银" and "民银行"


def test_hourly_enrich_uses_score_domain_ranking_module():
    hourly_dir = Path(__file__).resolve().parents[1] / "app" / "domains" / "enrich" / "hourly"
    offenders = []
    for path in hourly_dir.glob("*.py"):
        if "app.services.ranking_service" in path.read_text():
            offenders.append(path.name)
    assert offenders == []


def test_domain_notifications_do_not_import_service_layer():
    app_dir = Path(__file__).resolve().parents[1] / "app"
    checked = [
        app_dir / "domains" / "enrich" / "notifications" / "daily_digest.py",
        app_dir / "domains" / "enrich" / "notifications" / "doctor_digest.py",
        app_dir / "interfaces" / "http" / "system.py",
    ]
    offenders = []
    for path in checked:
        text = path.read_text()
        if (
            "app.services.digest_service" in text
            or "app.services.doctor_service" in text
            or "app.services.monitor_service" in text
        ):
            offenders.append(path.relative_to(app_dir).as_posix())
    assert offenders == []
