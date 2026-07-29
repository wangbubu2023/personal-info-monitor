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


def test_eval_release_tier_fails_closed_without_manifest_and_labels(tmp_path):
    dataset = tmp_path / "bootstrap.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "id": "inline-not-allowed",
                "url": "https://example.com/article",
                "source_type": "website",
                "language": "en",
                "paywall": "none",
                "case_type": "article",
                "html": "<html><body><article><p>Body text</p></article></body></html>",
                "gold": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = evaluate_jsonl(dataset, tier="web_clean_bootstrap")

    assert report["ok"] is False
    assert report["gate"]["result"] == "NO_GO"
    assert "manifest is missing" in report["gate"]["blockers"]
    assert report["metrics"]["must_include_recall"] == 0.0
    assert report["metrics"]["must_exclude_precision"] == 0.0
    assert "release dataset has no must_include labels" in report["gate"]["blockers"]


def test_eval_manifest_hash_and_fixture_contract_are_enforced(tmp_path):
    import hashlib

    fixture = tmp_path / "article.html"
    fixture.write_text("<html><body><article><p>Useful body paragraph.</p></article></body></html>", encoding="utf-8")
    dataset = tmp_path / "bootstrap.jsonl"
    row = {
        "id": "web-clean-001",
        "url": "https://example.com/article",
        "source_type": "website",
        "language": "en",
        "paywall": "none",
        "case_type": "article",
        "html_fixture": "article.html",
        "gold": {
            "must_include": ["Useful body"],
            "must_exclude": ["Advertisement"],
            "expected_status": "good",
        },
    }
    dataset.write_text(json.dumps(row) + "\n", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "dataset_tier": "web_clean_bootstrap",
                "sample_count": 1,
                "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
                "fixtures": {"article.html": "0" * 64},
            }
        ),
        encoding="utf-8",
    )

    report = evaluate_jsonl(dataset, manifest_path=manifest, tier="web_clean_bootstrap")

    assert report["manifest_valid"] is False
    assert "fixture hash mismatch: article.html" in report["gate"]["blockers"]
    assert report["gate"]["result"] == "NO_GO"


def test_eval_missing_manifest_path_fails_closed_without_exception(tmp_path):
    dataset = tmp_path / "eval.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "id": "web-clean-001",
                "url": "https://example.com/article",
                "html": "<article><p>Body</p></article>",
                "gold": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = evaluate_jsonl(
        dataset,
        manifest_path=tmp_path / "missing-manifest.json",
        tier="web_clean_eval_1_0",
    )

    assert report["ok"] is False
    assert report["manifest_sha256"] is None
    assert "manifest file is missing" in report["gate"]["blockers"]


def test_formal_gate_enforces_blocked_metadata_and_markdown_metrics():
    from app.domains.fetch.web_clean.eval import _gate_metrics

    metrics = {
        "sample_count": 150,
        "must_include_recall": 0.95,
        "must_exclude_precision": 0.95,
        "boilerplate_leak_rate": 0.01,
        "blocked_detection_f1": 0.87,
        "metadata_accuracy": 0.89,
        "markdown_structure_score": 0.84,
        "runtime_p95_ms": 10.0,
        "label_counts": {
            "must_include": 1,
            "must_exclude": 1,
            "quality_status": 1,
            "title": 1,
            "canonical_url": 1,
            "published_time": 1,
            "markdown": 1,
        },
    }

    blockers = _gate_metrics(
        metrics,
        tier="web_clean_eval_1_0",
        manifest={"baseline_runtime_p95_ms": 10.0},
        manifest_errors=[],
    )

    assert "formal blocked_detection_f1 is below 0.88" in blockers
    assert "formal metadata_accuracy is below 0.90" in blockers
    assert "formal markdown_structure_score is below 0.85" in blockers
