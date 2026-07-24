# Event Engine v1 operations

Event v1 is deployed in Shadow mode. Accepted content is assigned after durable
post-processing; the hourly Brief consumes persisted Events and Snapshots
instead of owning the assignment lifecycle.

## Safe defaults

- `EVENT_V1_ENABLED=true`
- `EVENT_V1_ASSIGNMENT=true`
- `EVENT_ASSIGNMENT_MODE=rules`
- `EVENT_V1_TODAY_READ=false`
- `EVENT_V1_READ_GATE_APPROVED=false`
- `EVENT_AUTO_MERGE_ENABLED=false`
- `EVENT_AUTO_SPLIT_ENABLED=false`
- cross-language, Storyline, embedding, and LLM judge flags are off

Today switches to v1 only when both read flags are true. Disabling either flag
immediately restores v0 reads without deleting v1 memberships, aliases,
operations, Snapshots, or diff audits.

## Operator surfaces

- `GET /api/events/config`: effective versions, thresholds, TTLs, weights, and flags.
- `GET /api/events/shadow/today-preview`: internal canonical Snapshot preview.
- `GET /api/events/resolve/{event_ref}`: canonical, redirect, or split mapping.
- `POST /api/events/operations/merge`: audited manual merge.
- `POST /api/events/{event_id}/operations/split`: audited explicit partition.
- `POST /api/events/{event_id}/operations/lifecycle`: close or reopen.
- `POST /api/events/operations/{operation_id}/revert`: reversible merge, split, or lifecycle operation.
- `POST /api/events/rebalance`: bounded light/deep suggestion run.
- `GET /api/events/rebalance/runs`: budgets, cursor, counts, and checkpoints.
- diagnostic endpoints are hidden unless `EVENT_DEBUG_EXPLAIN_ENABLED=true`.

All HTTP surfaces remain protected by the normal API authentication layer.

## Backfill and performance

```bash
cd backend
.venv/bin/python scripts/backfill_event_v1.py \
  --batch-size 100 \
  --checkpoint ~/.pim/data/event-v1-backfill-checkpoint.json

.venv/bin/python scripts/benchmark_m3_event_engine.py
```

Backfill is ordered by `(created_at, content_id)`, checkpointed, checksummed,
idempotent, and Shadow-only. The benchmark must report zero closed/archived
pair comparisons and stop safely at the configured pair/runtime budget.

## Read-switch gate

Do not approve `EVENT_V1_READ_GATE_APPROVED` until all are true:

1. formal Event Eval has at least 50 clusters and 200 pairs;
2. Wrong Merge is below 3%;
3. Missing Merge is below 8%;
4. ID Churn is stable for seven consecutive production days;
5. v0/v1 Today diffs have passed human sampling;
6. rollback has been rehearsed by disabling the read flag.

P3 experiments require four stable weeks and a separate review.
