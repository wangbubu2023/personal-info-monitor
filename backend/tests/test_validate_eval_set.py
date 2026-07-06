from __future__ import annotations

import json

from scripts.validate_eval_set import install_eval_set, validate_eval_set


def _record(idx: int, **overrides):
    base = {
        "id": f"candidate-{idx}",
        "title": f"Story {idx}",
        "url": f"https://source{idx}.example/story",
        "label": "ok",
        "article_score": 100 - idx,
        "source_id": f"source-{idx}",
        "summary": "summary",
        "full_content": "body " * 80,
        "metadata": {"fulltext_status": "full"},
    }
    base.update(overrides)
    return base


def _write_jsonl(path, rows):
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")


def test_validate_eval_set_accepts_labeled_diverse_set(tmp_path):
    path = tmp_path / "annotated.jsonl"
    rows = [_record(1, label="must_see"), _record(2, label="noise"), _record(3, label="ok")]
    _write_jsonl(path, rows)

    result = validate_eval_set(path, min_records=3, min_sources=3)

    assert result.ok
    assert result.errors == []
    assert result.metrics["total"] == 3
    assert result.metrics["source_diversity@20"] == 3


def test_validate_eval_set_reports_missing_labels_duplicates_and_shortfall(tmp_path):
    path = tmp_path / "bad.jsonl"
    rows = [
        _record(1, label=""),
        _record(2, id="candidate-1", source_id="source-1", title="", url=""),
    ]
    _write_jsonl(path, rows)

    result = validate_eval_set(path, min_records=3, min_sources=2)

    assert not result.ok
    assert "expected at least 3 records, found 2" in result.errors
    assert "line 1: label is required" in result.errors
    assert "line 2: duplicate id 'candidate-1'; first seen on line 1" in result.errors
    assert "line 2: title is required" in result.errors
    assert "line 2: url is required" in result.errors
    assert "expected at least 2 sources, found 1" in result.errors


def test_install_eval_set_writes_sorted_jsonl(tmp_path):
    output = tmp_path / "eval_set.jsonl"
    rows = [_record(2), _record(1, label="must_see")]

    install_eval_set(rows, output)

    written = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert written == rows
