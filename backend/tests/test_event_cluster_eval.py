import json

from scripts.run_event_cluster_eval import (
    EVENT_CLUSTER_AGENT_BRIEF,
    EVENT_CLUSTER_EVAL_STANDARD,
    run_pairwise_eval,
    validate_event_cluster_dataset,
)


def _pair(idx: int, *, same_event: bool, event_id: str, case_type: str) -> dict:
    suffix = "same" if same_event else "different"
    return {
        "id": f"pair-{idx}",
        "event_id": event_id,
        "case_type": case_type,
        "same_event": same_event,
        "left": {
            "id": f"left-{idx}",
            "title": f"Company A launches model {idx}",
            "summary": "A new model was released with official details.",
            "source_name": "Official",
        },
        "right": {
            "id": f"right-{idx}",
            "title": f"Company A launches model {idx if same_event else idx + 100}",
            "summary": f"A {suffix} model story with related company terms.",
            "source_name": "Wire",
        },
    }


def test_event_cluster_eval_standard_documents_required_coverage():
    assert EVENT_CLUSTER_EVAL_STANDARD["min_event_clusters"] == 50
    assert EVENT_CLUSTER_EVAL_STANDARD["min_pairs"] == 200
    assert "cross_language" in EVENT_CLUSTER_EVAL_STANDARD["coverage"]
    assert "same_company_different_event" in EVENT_CLUSTER_EVAL_STANDARD["coverage"]
    assert "continuous_version_release" in EVENT_CLUSTER_EVAL_STANDARD["coverage"]
    assert EVENT_CLUSTER_EVAL_STANDARD["maintenance"]["agent_brief_command"]
    assert "Duplicate groups are article-level" in EVENT_CLUSTER_AGENT_BRIEF


def test_validate_event_cluster_dataset_reports_missing_coverage():
    rows = [_pair(1, same_event=True, event_id="event-1", case_type="cross_language")]

    errors = validate_event_cluster_dataset(rows, min_pairs=1, min_clusters=1)

    assert "missing coverage case_type=same_company_different_event" in errors
    assert "missing coverage case_type=continuous_version_release" in errors


def test_validate_event_cluster_dataset_accepts_minimal_complete_set():
    rows = [
        _pair(1, same_event=True, event_id="event-1", case_type="cross_language"),
        _pair(2, same_event=False, event_id="event-2", case_type="same_company_different_event"),
        _pair(3, same_event=True, event_id="event-3", case_type="continuous_version_release"),
    ]

    assert validate_event_cluster_dataset(rows, min_pairs=3, min_clusters=3) == []


def test_pairwise_eval_outputs_metrics():
    rows = [
        _pair(1, same_event=True, event_id="event-1", case_type="cross_language"),
        _pair(2, same_event=False, event_id="event-2", case_type="same_company_different_event"),
    ]

    metrics = run_pairwise_eval(rows, threshold=0.28)

    assert metrics["total_pairs"] == 2
    assert set(metrics).issuperset({"precision", "recall", "accuracy", "tp", "fp", "tn", "fn"})
    json.dumps(metrics)
