import json

from app.domains.fetch.web_clean.eval import evaluate_jsonl


def test_eval_runner_scores_golden_contract(tmp_path):
    fixture = tmp_path / "article.html"
    fixture.write_text(
        """
        <html><head><meta property="og:title" content="Golden article"></head>
        <body><nav>Advertisement</nav><article>
        <h1>Golden article</h1>
        <p>Critical paragraph A contains the essential result and detailed context.</p>
        <p>Critical paragraph B explains the evidence and its practical implications.</p>
        <p>A final substantial paragraph makes the extracted article long enough to classify.</p>
        </article><footer>Related articles</footer></body></html>
        """,
        encoding="utf-8",
    )
    dataset = tmp_path / "eval.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "id": "web-clean-001",
                "url": "https://example.com/article/1",
                "html_fixture": "article.html",
                "gold": {
                    "title": "Golden article",
                    "must_include": ["Critical paragraph A", "Critical paragraph B"],
                    "must_exclude": ["Advertisement", "Related articles"],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    report = evaluate_jsonl(dataset)
    assert report["metrics"]["sample_count"] == 1
    assert report["metrics"]["must_include_recall"] == 1.0
    assert report["metrics"]["must_exclude_precision"] == 1.0
    assert report["metrics"]["title_accuracy"] == 1.0
