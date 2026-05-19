from app.services.ranking_service import RankingService


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
