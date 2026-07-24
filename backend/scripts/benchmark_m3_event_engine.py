#!/usr/bin/env python3
"""Synthetic M3 deep-rebalance budget check (10k historical + 1k active)."""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.domains.events.rebalance import run_rebalance
from app.models import ContentEvent
from app.utils.datetime import utcnow_naive


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--historical", type=int, default=10_000)
    parser.add_argument("--active", type=int, default=1_000)
    parser.add_argument("--max-pairs", type=int, default=5_000)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="pim-m3-benchmark-") as folder:
        engine = create_engine(f"sqlite:///{Path(folder) / 'event.db'}")
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine)
        with factory() as db:
            now = utcnow_naive()
            rows = []
            for index in range(max(0, args.historical)):
                rows.append(
                    ContentEvent(
                        event_id=f"h{index:031d}",
                        event_key=f"historical-{index}",
                        title=f"Historical {index}",
                        status="closed",
                        cluster_version="event-v1.0-rules",
                        last_material_update_at=now,
                        centroid={"tokens": [f"historical-{index}"], "signature": {}},
                        created_at=now,
                        updated_at=now,
                    )
                )
            for index in range(max(0, args.active)):
                block = index // 10
                rows.append(
                    ContentEvent(
                        event_id=f"a{index:031d}",
                        event_key=f"active-{index}",
                        title=f"Active {index}",
                        status="active",
                        cluster_version="event-v1.0-rules",
                        last_material_update_at=now,
                        centroid={
                            "tokens": [f"entity-{block}", f"item-{index}"],
                            "signature": {
                                "normalized_entities": [
                                    {"canonical_id": f"entity-{block}", "surface": f"Entity {block}"}
                                ],
                                "identifiers": [],
                                "trigger_action": {"lemma": "launch"},
                            },
                        },
                        created_at=now,
                        updated_at=now,
                    )
                )
            db.bulk_save_objects(rows)
            db.commit()
            started = time.perf_counter()
            result = run_rebalance(
                db,
                run_kind="deep",
                max_events=args.active,
                max_pairs=args.max_pairs,
                max_runtime_seconds=60,
                checkpoint_size=100,
            )
            db.commit()
            result["wall_seconds"] = round(time.perf_counter() - started, 3)
            result["historical_event_count"] = args.historical
            result["active_event_count"] = args.active
            result["cartesian_pair_count_avoided"] = (
                (args.historical + args.active) * (args.historical + args.active - 1) // 2
                - result["candidate_pair_count"]
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            if result["filtered_closed_count"] != args.historical:
                return 2
            if result["candidate_pair_count"] > args.max_pairs:
                return 3
            if result["closed_pair_comparisons"] != 0:
                return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
