from __future__ import annotations

import csv
import json

import pytest

from scripts.review_eval_candidates import (
    REVIEW_COLUMNS,
    apply_review_rows,
    build_review_rows,
    load_review_sheet,
    review_status,
    write_review_html,
    write_review_sheet,
)


def _candidate(idx: int, **overrides):
    record = {
        "id": f"candidate-{idx}",
        "title": f"Story {idx}",
        "summary": f"Useful summary {idx}",
        "full_content": "Full body " * 80,
        "url": f"https://example.com/{idx}",
        "label": "",
        "suggested_label": "ok",
        "suggested_confidence": 0.7,
        "suggested_reason": "moderate score",
        "review_priority": "medium",
        "source_name": "Example",
        "source_id": f"source-{idx}",
    }
    record.update(overrides)
    return record


def test_build_review_rows_sorts_priority_and_skips_labeled():
    records = [
        _candidate(1, review_priority="low", suggested_confidence=0.99),
        _candidate(2, review_priority="high", suggested_confidence=0.6),
        _candidate(3, label="ok", review_priority="high", suggested_confidence=0.95),
        _candidate(4, review_priority="medium", suggested_label=""),
    ]

    rows, stats = build_review_rows(records, max_summary_chars=20)

    assert [row["id"] for row in rows] == ["candidate-2", "candidate-4", "candidate-1"]
    assert rows[1]["suggested_label"] == ""
    assert rows[0]["summary"] == "Useful summary 2"
    assert stats["records"] == 4
    assert stats["exported"] == 3
    assert stats["skipped_labeled"] == 1
    assert stats["missing_suggestions"] == 1
    assert stats["by_priority"] == {"high": 1, "low": 1, "medium": 1}


def test_write_and_load_review_sheet_round_trips_tsv(tmp_path):
    path = tmp_path / "review.tsv"
    rows = [
        dict.fromkeys(REVIEW_COLUMNS, ""),
        dict.fromkeys(REVIEW_COLUMNS, ""),
    ]
    rows[0].update({"id": "candidate-1", "label": "must_see", "title": "One"})
    rows[1].update({"id": "candidate-2", "label": "noise", "title": "Two"})

    write_review_sheet(path, rows)
    loaded = load_review_sheet(path)

    assert loaded == rows
    with path.open("r", encoding="utf-8", newline="") as handle:
        assert next(csv.reader(handle, delimiter="\t")) == REVIEW_COLUMNS


def test_write_review_html_embeds_rows_and_escapes_script_close(tmp_path):
    path = tmp_path / "review.html"
    rows = [
        dict.fromkeys(REVIEW_COLUMNS, ""),
        dict.fromkeys(REVIEW_COLUMNS, ""),
    ]
    rows[0].update(
        {
            "id": "candidate-1",
            "label": "",
            "title": "Unsafe </script> title",
            "suggested_label": "must_see",
            "review_priority": "high",
        }
    )
    rows[1].update({"id": "candidate-2", "label": "ok", "title": "Two"})

    write_review_html(path, rows, {"exported": 2})

    html = path.read_text(encoding="utf-8")
    assert "<title>PIM Eval Review</title>" in html
    assert "Download TSV" in html
    assert "candidate-1" in html
    assert "<\\/script> title" in html
    assert "const payload = " in html
    assert "data-label=\"must_see\"" in html


def test_apply_review_rows_updates_labels_without_touching_unreviewed():
    records = [_candidate(1), _candidate(2), _candidate(3, label="ok")]
    rows = [
        {"id": "candidate-1", "label": "must_see"},
        {"id": "candidate-2", "label": ""},
        {"id": "candidate-3", "label": "noise"},
    ]

    annotated, stats = apply_review_rows(records, rows)

    assert [record.get("label") for record in annotated] == ["must_see", "", "noise"]
    assert annotated[0]["label_source"] == "human-review-sheet-v1"
    assert annotated[2]["label_source"] == "human-review-sheet-v1"
    assert stats["updated_labels"] == 2
    assert stats["remaining_unlabeled"] == 1
    assert stats["labels"] == {"must_see": 1, "noise": 1}


def test_apply_review_rows_can_require_every_sheet_row_to_be_labeled():
    records = [_candidate(1)]

    with pytest.raises(ValueError, match="label is required"):
        apply_review_rows(records, [{"id": "candidate-1", "label": ""}], require_reviewed=True)


def test_apply_review_rows_rejects_unknown_id_and_invalid_label():
    records = [_candidate(1)]

    with pytest.raises(ValueError) as excinfo:
        apply_review_rows(
            records,
            [
                {"id": "candidate-1", "label": "maybe"},
                {"id": "candidate-404", "label": "ok"},
            ],
        )

    message = str(excinfo.value)
    assert "label must be one of" in message
    assert "unknown id 'candidate-404'" in message


def test_apply_review_rows_output_is_json_serializable():
    annotated, _ = apply_review_rows([_candidate(1)], [{"id": "candidate-1", "label": "ok"}])

    assert json.loads(json.dumps(annotated[0]))["label"] == "ok"


def test_review_status_reports_progress_from_sheet_labels():
    records = [
        _candidate(1, review_priority="high", suggested_label="must_see"),
        _candidate(2, review_priority="medium", suggested_label="ok"),
        _candidate(3, review_priority="low", suggested_label="noise"),
    ]
    rows = [
        {"id": "candidate-1", "label": "must_see"},
        {"id": "candidate-2", "label": ""},
        {"id": "candidate-3", "label": "noise"},
    ]

    stats = review_status(records, rows)

    assert not stats["ok"]
    assert stats["records"] == 3
    assert stats["review_rows"] == 3
    assert stats["labeled"] == 2
    assert stats["remaining_unlabeled"] == 1
    assert stats["labels"] == {"must_see": 1, "noise": 1}
    assert stats["missing_by_priority"] == {"medium": 1}
    assert stats["missing_by_suggestion"] == {"ok": 1}
    assert stats["errors"] == []


def test_review_status_accepts_complete_jsonl_without_sheet():
    records = [_candidate(1, label="ok"), _candidate(2, label="noise")]

    stats = review_status(records)

    assert stats["ok"]
    assert stats["review_rows"] is None
    assert stats["remaining_unlabeled"] == 0
    assert stats["labels"] == {"noise": 1, "ok": 1}


def test_review_status_reports_sheet_integrity_errors():
    records = [_candidate(1), _candidate(2)]
    rows = [
        {"id": "candidate-1", "label": "maybe"},
        {"id": "candidate-1", "label": "ok"},
        {"id": "candidate-404", "label": "ok"},
    ]

    stats = review_status(records, rows)

    assert not stats["ok"]
    assert stats["remaining_unlabeled"] == 2
    assert stats["error_count"] == 4
    assert any("label must be one of" in error for error in stats["errors"])
    assert "sheet row 3: duplicate id 'candidate-1'" in stats["errors"]
    assert "sheet row 4: unknown id 'candidate-404'" in stats["errors"]
    assert any("sheet is missing 1 candidate ids: candidate-2" == error for error in stats["errors"])
