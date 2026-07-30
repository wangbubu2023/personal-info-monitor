#!/usr/bin/env python3
"""Export explicit inline labels and adjudications as a versioned eval asset."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import AnnotationTask
from app.platform.persistence.database import SessionLocal
from app.utils.datetime import to_iso_z


DEFAULT_OUTPUT = Path.home() / ".pim" / "data" / "eval" / "gold" / "annotation_eval_latest.jsonl"


def _split(task_id: str) -> str:
    bucket = int(hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:8], 16) % 10
    if bucket == 0:
        return "test"
    if bucket == 1:
        return "validation"
    return "train"


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_rows() -> list[dict[str, Any]]:
    with SessionLocal() as db:
        tasks = (
            db.execute(
                select(AnnotationTask)
                .options(
                    selectinload(AnnotationTask.labels),
                    selectinload(AnnotationTask.adjudication),
                )
                .where(AnnotationTask.status.in_(("labeled", "adjudicated")))
                .order_by(AnnotationTask.created_at.asc())
            )
            .scalars()
            .all()
        )
        rows = []
        for task in tasks:
            if task.adjudication is not None:
                payload = task.adjudication.final_payload
                label_source = "human-adjudication-v1"
                annotator = task.adjudication.adjudicator
                labeled_at = task.adjudication.created_at
                gold_candidate = bool(task.adjudication.gold_candidate)
            elif task.labels:
                latest = task.labels[-1]
                payload = latest.label_payload
                label_source = "inline-human-v1"
                annotator = latest.annotator
                labeled_at = latest.created_at
                gold_candidate = True
            else:
                continue
            if not gold_candidate:
                continue
            rows.append(
                {
                    "annotation_task_id": str(task.id),
                    "task_type": task.task_type,
                    "target_type": task.target_type,
                    "target_id": task.target_id,
                    "secondary_target_id": task.secondary_target_id,
                    "schema_version": task.schema_version,
                    "split": _split(str(task.id)),
                    "gold": payload,
                    "context_snapshot": task.context_snapshot,
                    "prediction_snapshot": task.prediction_snapshot,
                    "label_source": label_source,
                    "annotator": annotator,
                    "labeled_at": to_iso_z(labeled_at),
                    "source_dataset": task.source_dataset,
                }
            )
        return rows


def export(output: Path) -> tuple[Path, Path]:
    rows = build_rows()
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(output.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    temp.replace(output)
    counts = Counter(str(row["task_type"]) for row in rows)
    split_counts = Counter(str(row["split"]) for row in rows)
    manifest_path = output.with_name(f"{output.stem}_manifest.json")
    manifest = {
        "schema_version": "pim_annotation_eval_manifest_v1",
        "dataset": output.name,
        "dataset_sha256": _sha256(output),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(),
        "record_count": len(rows),
        "task_type_counts": dict(sorted(counts.items())),
        "split_counts": dict(sorted(split_counts.items())),
        "label_sources": sorted({str(row["label_source"]) for row in rows}),
        "limitations": [
            "Single-user inline labels are explicit human judgments but are not double annotated.",
            "Only conflicts and imported ambiguous samples require adjudication.",
        ],
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output, manifest_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output, manifest = export(args.output.expanduser())
    print(output)
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
