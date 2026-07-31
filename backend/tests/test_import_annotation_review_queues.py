import json

from scripts.import_annotation_review_queues import build_tasks


def test_event_conflicting_annotations_are_imported_for_adjudication(tmp_path):
    row = {
        "pair_id": "event-conflict-1",
        "review_reason": "conflicting_annotations",
        "annotation_context": [
            {"tier": "bootstrap", "event_correctness": "partial"},
            {"tier": "formal", "event_correctness": "incorrect"},
        ],
        "event": {"title": "Conflicting event"},
    }
    (tmp_path / "event_card_correctness_v0_1_needs_review.jsonl").write_text(
        json.dumps(row, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    candidates = build_tasks(tmp_path)

    assert len(candidates) == 1
    task, labels = candidates[0]
    assert task.status == "needs_adjudication"
    assert [label.label_payload["value"] for label in labels] == ["partial", "incorrect"]
