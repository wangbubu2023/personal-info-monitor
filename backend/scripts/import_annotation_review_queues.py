#!/usr/bin/env python3
"""Import existing JSONL review queues into the development annotation loop.

The import is idempotent. Source files are never modified, and task
fingerprints prevent duplicate queue entries across repeated runs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import select

from app.models import AnnotationLabel, AnnotationTask
from app.platform.persistence.database import SessionLocal
from app.utils.datetime import utcnow_naive


DEFAULT_QUEUE_DIR = Path.home() / ".pim" / "data" / "eval" / "gold" / "review_queues"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: expected JSON object")
        rows.append(value)
    return rows


def _fingerprint(target_type: str, target_id: str, secondary_target_id: str | None = None) -> str:
    raw = "\x1f".join((target_type, target_id, secondary_target_id or ""))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _task(
    *,
    task_type: str,
    target_type: str,
    target_id: str,
    status: str,
    reason: str,
    context: dict[str, Any],
    source_dataset: str,
    priority: float,
    labels: Iterable[tuple[str, str]] = (),
) -> tuple[AnnotationTask, list[AnnotationLabel]]:
    now = utcnow_naive()
    task = AnnotationTask(
        task_type=task_type,
        target_type=target_type,
        target_id=target_id,
        target_fingerprint=_fingerprint(target_type, target_id),
        schema_version="v1",
        status=status,
        priority=priority,
        reason=reason,
        context_snapshot=context,
        prediction_snapshot={},
        source_dataset=source_dataset,
        created_at=now,
        updated_at=now,
    )
    task_labels = [
        AnnotationLabel(
            task=task,
            annotator=annotator,
            label_payload={"value": value},
            created_at=now,
        )
        for annotator, value in labels
    ]
    return task, task_labels


def build_tasks(queue_dir: Path) -> list[tuple[AnnotationTask, list[AnnotationLabel]]]:
    tasks: list[tuple[AnnotationTask, list[AnnotationLabel]]] = []

    core_path = queue_dir / "core_quality_adjudication_v0_1.jsonl"
    for row in _read_jsonl(core_path):
        sample_id = str(row.get("sample_id") or "").strip()
        if not sample_id:
            continue
        conflicts = row.get("conflicts") if isinstance(row.get("conflicts"), dict) else {}
        annotation_sources = row.get("annotation_sources") if isinstance(row.get("annotation_sources"), list) else []
        for dimension in ("relevance", "quality", "fact_density"):
            if not conflicts.get(dimension):
                continue
            labels = []
            for index, source in enumerate(annotation_sources):
                if not isinstance(source, dict) or not source.get(dimension):
                    continue
                labels.append((f"imported-{source.get('tier') or index}", str(source[dimension])))
            tasks.append(
                _task(
                    task_type=f"content_{dimension}",
                    target_type="content",
                    target_id=sample_id,
                    status="needs_adjudication",
                    reason="conflicting imported human labels",
                    context=row,
                    source_dataset=core_path.name,
                    priority=100,
                    labels=labels,
                )
            )

    lane_path = queue_dir / "lane_eval_v0_1_needs_review.jsonl"
    for row in _read_jsonl(lane_path):
        sample_id = str(row.get("sample_id") or "").strip()
        if not sample_id:
            continue
        tasks.append(
            _task(
                task_type="content_lane",
                target_type="content",
                target_id=sample_id,
                status="pending",
                reason=str(row.get("review_reason") or "new taxonomy requires direct label"),
                context=row,
                source_dataset=lane_path.name,
                priority=50,
            )
        )

    event_path = queue_dir / "event_card_correctness_v0_1_needs_review.jsonl"
    for row in _read_jsonl(event_path):
        target_id = str(row.get("pair_id") or "").strip()
        if not target_id:
            continue
        labels = []
        for index, source in enumerate(row.get("annotation_context") or []):
            if not isinstance(source, dict):
                continue
            value = str(source.get("event_correctness") or "").strip()
            if value:
                labels.append((f"imported-{source.get('tier') or index}", value))
        status = (
            "needs_adjudication"
            if row.get("review_reason") in {"conflict", "conflicting_annotations"}
            else "pending"
        )
        tasks.append(
            _task(
                task_type="event_correctness",
                target_type="event",
                target_id=target_id,
                status=status,
                reason=str(row.get("review_reason") or "event card needs direct review"),
                context=row,
                source_dataset=event_path.name,
                priority=75 if status == "needs_adjudication" else 40,
                labels=labels if status == "needs_adjudication" else (),
            )
        )

    return tasks


def import_tasks(queue_dir: Path, *, apply: bool) -> dict[str, int]:
    candidates = build_tasks(queue_dir)
    summary = {"candidates": len(candidates), "created": 0, "existing": 0}
    if not apply:
        return summary

    with SessionLocal() as db:
        for task, labels in candidates:
            existing = db.execute(
                select(AnnotationTask.id).where(
                    AnnotationTask.task_type == task.task_type,
                    AnnotationTask.target_fingerprint == task.target_fingerprint,
                    AnnotationTask.schema_version == task.schema_version,
                )
            ).scalar_one_or_none()
            if existing:
                summary["existing"] += 1
                existing_task = db.get(AnnotationTask, existing)
                if existing_task and task.status == "needs_adjudication":
                    existing_task.status = "needs_adjudication"
                    existing_task.priority = max(float(existing_task.priority or 0), float(task.priority or 0))
                    existing_task.updated_at = utcnow_naive()
                    existing_labels = {
                        (
                            str(label.annotator),
                            str((label.label_payload or {}).get("value") or ""),
                        )
                        for label in existing_task.labels
                    }
                    for label in labels:
                        key = (
                            str(label.annotator),
                            str((label.label_payload or {}).get("value") or ""),
                        )
                        if key not in existing_labels:
                            label.task = existing_task
                            db.add(label)
                            existing_labels.add(key)
                continue
            db.add(task)
            db.add_all(labels)
            summary["created"] += 1
        db.commit()
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue-dir", type=Path, default=DEFAULT_QUEUE_DIR)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    summary = import_tasks(args.queue_dir.expanduser(), apply=args.apply)
    mode = "imported" if args.apply else "dry-run"
    print(f"{mode}: {json.dumps(summary, ensure_ascii=False, sort_keys=True)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
