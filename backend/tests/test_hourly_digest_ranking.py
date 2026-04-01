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
            "source_priority": 1,
        },
        {
            "title": "AI chip export policy tightened by US government",
            "summary": "Several regions and companies face expanded restrictions.",
            "source_name": "SourceB",
            "source_url": "https://b.example.com",
            "article_url": "https://b.example.com/us-export-policy",
            "source_priority": 1,
        },
        {
            "title": "Local startup raises series A",
            "summary": "Funding round details.",
            "source_name": "SourceC",
            "source_url": "https://c.example.com",
            "article_url": "https://c.example.com/startup-series-a",
            "source_priority": 1,
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
            "source_priority": 1,
        },
        {
            "title": "Central bank leaves interest rates steady",
            "summary": "Market reaction remains mixed.",
            "source_name": "SourceB",
            "source_url": "https://b.example.com",
            "article_url": "https://b.example.com/rates-steady",
            "source_priority": 1,
        },
    ]

    baseline = service.cluster_and_rank(entries)
    assert baseline

    excluded = {cluster["event_key"] for cluster in baseline}
    filtered = service.cluster_and_rank(entries, excluded_event_keys=excluded)
    assert filtered == []
