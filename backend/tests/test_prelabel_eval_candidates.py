from __future__ import annotations

import json

from scripts.prelabel_eval_candidates import prelabel_records, suggest_label


def _candidate(idx: int, **overrides):
    record = {
        "id": f"candidate-{idx}",
        "title": f"Story {idx}",
        "summary": "Useful summary",
        "url": f"https://example.com/{idx}",
        "label": "",
        "article_score": 60,
        "source_name": "Example",
        "source_id": f"source-{idx}",
        "metadata": {"fulltext_status": "full"},
        "source_metadata": {},
    }
    record.update(overrides)
    return record


def test_suggest_label_marks_duplicate_as_noise():
    suggestion = suggest_label(_candidate(1, metadata={"duplicate_group_id": "same-story"}))

    assert suggestion.label == "noise"
    assert suggestion.confidence >= 0.8
    assert "duplicate" in suggestion.reason


def test_suggest_label_marks_high_score_as_must_see():
    suggestion = suggest_label(_candidate(1, article_score=91, title="Central bank policy update"))

    assert suggestion.label == "must_see"
    assert suggestion.review_priority == "high"


def test_prelabel_records_adds_suggestions_without_setting_final_label():
    records = [
        _candidate(1, article_score=91, title="OpenAI announces model update"),
        _candidate(2, article_score=20, title="Promo: discounted gadget bundle"),
        _candidate(3, label="ok", suggested_label="must_see", review_priority="high"),
    ]

    labeled, stats = prelabel_records(records)

    assert [item["label"] for item in labeled] == ["", "", "ok"]
    assert labeled[0]["suggested_label"] == "must_see"
    assert labeled[1]["suggested_label"] == "noise"
    assert labeled[2]["suggested_label"] == "must_see"
    assert stats["already_labeled"] == 1
    assert stats["suggested_labels"]["must_see"] == 2


def test_prelabel_records_overwrites_existing_suggestions():
    records = [_candidate(1, suggested_label="noise", review_priority="low", article_score=91)]

    labeled, stats = prelabel_records(records, overwrite_suggestions=True)

    assert labeled[0]["suggested_label"] == "must_see"
    assert stats["suggested_labels"] == {"must_see": 1}


def test_prelabel_output_records_remain_json_serializable():
    labeled, _ = prelabel_records([_candidate(1, title="Newsletter roundup", article_score=10)])

    assert json.loads(json.dumps(labeled[0]))["suggested_label"] == "noise"
