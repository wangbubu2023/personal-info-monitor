"""Run pairwise Event clustering evaluation.

Dataset JSONL contract (P1-02):
- one record per pair
- required: left, right, same_event
- left/right require id, title; summary/source_name/publish_time are optional
- optional: case_type, notes, event_id

The script is intentionally standalone so future production agents can install a
human-reviewed event pair set without touching app runtime code.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.domains.score.ranking import RankingService

DEFAULT_DATASET = ROOT / "tests" / "fixtures" / "event_cluster_pairs.jsonl"

EVENT_CLUSTER_EVAL_STANDARD = {
    "min_event_clusters": 50,
    "min_pairs": 200,
    "required_pair_fields": ["left", "right", "same_event"],
    "required_item_fields": ["id", "title"],
    "coverage": ["cross_language", "same_company_different_event", "continuous_version_release"],
    "labels": {"same_event": "两条报道属于同一现实事件", "different_event": "相似实体/公司/主题但不是同一事件"},
    "maintenance": {
        "install_path": str(DEFAULT_DATASET.relative_to(ROOT)),
        "refresh_rule": "重大 scoring/dedupe/event signature 改动后刷新；活跃迭代期按月扩展。",
        "agent_brief_command": "python scripts/run_event_cluster_eval.py --print-agent-brief",
    },
}


EVENT_CLUSTER_AGENT_BRIEF = """\
P1-02 Event clustering pair dataset brief for production agents

Goal:
- Build backend/tests/fixtures/event_cluster_pairs.jsonl for pairwise event clustering eval.
- Minimum: 50 real-world event clusters and 200 human-reviewed pairs.

Required JSONL shape:
- One JSON object per pair.
- Required pair fields: id, event_id, case_type, same_event, left, right.
- left/right require: id, title. Recommended: summary, source_name, source_url, publish_time, url, language, metadata.

Coverage:
- cross_language: same event across Chinese/English or translated reporting.
- same_company_different_event: same company/entity but different launches/incidents/announcements.
- continuous_version_release: consecutive model/product/policy versions that may look similar but need precise event boundaries.

Label policy:
- same_event=true only when both reports describe the same real-world occurrence.
- Do not use duplicate_group_id as the event label. Duplicate groups are article-level near-duplicate evidence only.
- Suggested labels from automation must be stored as suggested_* and are not final until human review.

Maintenance:
- Prefer adding a new dataset version over mutating old labels silently.
- If changing an existing pair label, add annotation_notes explaining why.
- Re-run this script after scoring, dedupe, event signature, multilingual tokenization, or threshold changes.
"""


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"line {line_no}: invalid JSON") from exc
    return rows


def _entry(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "content_id": str(raw.get("id") or raw.get("content_id") or ""),
        "title": str(raw.get("title") or ""),
        "summary": str(raw.get("summary") or ""),
        "source_name": str(raw.get("source_name") or ""),
        "source_url": str(raw.get("source_url") or ""),
        "article_score": raw.get("article_score", 70),
        "metadata": raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
    }


def validate_event_cluster_dataset(rows: list[dict[str, Any]], *, min_pairs: int = 200, min_clusters: int = 50) -> list[str]:
    errors: list[str] = []
    if len(rows) < min_pairs:
        errors.append(f"expected at least {min_pairs} pairs, found {len(rows)}")
    cluster_ids = {str(row.get("event_id") or "").strip() for row in rows if row.get("event_id")}
    if len(cluster_ids) < min_clusters:
        errors.append(f"expected at least {min_clusters} event clusters, found {len(cluster_ids)}")
    case_types = {str(row.get("case_type") or "").strip() for row in rows}
    for required in EVENT_CLUSTER_EVAL_STANDARD["coverage"]:
        if required not in case_types:
            errors.append(f"missing coverage case_type={required}")
    for idx, row in enumerate(rows, start=1):
        for field in EVENT_CLUSTER_EVAL_STANDARD["required_pair_fields"]:
            if field not in row:
                errors.append(f"pair {idx}: missing {field}")
        for side in ("left", "right"):
            item = row.get(side)
            if not isinstance(item, dict):
                errors.append(f"pair {idx}: {side} must be object")
                continue
            for field in EVENT_CLUSTER_EVAL_STANDARD["required_item_fields"]:
                if not str(item.get(field) or "").strip():
                    errors.append(f"pair {idx}: {side}.{field} is required")
    return errors


def run_pairwise_eval(rows: list[dict[str, Any]], *, threshold: float = 0.28) -> dict[str, Any]:
    service = RankingService(similarity_threshold=threshold)
    tp = fp = tn = fn = 0
    cases: list[dict[str, Any]] = []
    for row in rows:
        left = _entry(row["left"])
        right = _entry(row["right"])
        clusters = service.cluster_and_rank([left, right])
        predicted_same = len(clusters) == 1
        expected_same = bool(row["same_event"])
        if predicted_same and expected_same:
            tp += 1
        elif predicted_same and not expected_same:
            fp += 1
        elif not predicted_same and expected_same:
            fn += 1
        else:
            tn += 1
        cases.append({"id": row.get("id"), "expected_same": expected_same, "predicted_same": predicted_same})
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    accuracy = (tp + tn) / len(rows) if rows else 0.0
    return {
        "total_pairs": len(rows),
        "threshold": threshold,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "accuracy": round(accuracy, 4),
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "cases": cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Event pairwise clustering eval")
    parser.add_argument("dataset", nargs="?", default=str(DEFAULT_DATASET))
    parser.add_argument("--threshold", type=float, default=0.28)
    parser.add_argument("--min-pairs", type=int, default=200)
    parser.add_argument("--min-clusters", type=int, default=50)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--print-standard", action="store_true")
    parser.add_argument("--print-agent-brief", action="store_true")
    args = parser.parse_args()
    if args.print_agent_brief:
        print(EVENT_CLUSTER_AGENT_BRIEF)
        return 0
    if args.print_standard:
        print(json.dumps(EVENT_CLUSTER_EVAL_STANDARD, ensure_ascii=False, indent=2))
        return 0
    path = Path(args.dataset)
    if not path.exists():
        payload = {"ok": False, "errors": [f"dataset not installed: {path}"]}
        print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else payload["errors"][0])
        return 1
    rows = _load_jsonl(path)
    errors = validate_event_cluster_dataset(rows, min_pairs=args.min_pairs, min_clusters=args.min_clusters)
    if errors:
        payload = {"ok": False, "errors": errors, "standard": EVENT_CLUSTER_EVAL_STANDARD}
        print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else "\n".join(errors))
        return 1
    metrics = run_pairwise_eval(rows, threshold=args.threshold)
    payload = {"ok": True, "metrics": metrics}
    print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else json.dumps(metrics, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
