# ADR: Event v0 → v1 Migration Contract

- Status: Accepted for M1 implementation
- Date: 2026-07-23
- Scope: schema expansion and migration safety only; Today continues reading v0

## Decision

Event identity becomes immutable. `content_events.event_id` remains the stable
canonical ID; mutable `event_key` values and historical URLs are represented by
`event_aliases`. Merge, split, correction, backfill, and rollback actions are
append-only `event_operations`. v1 assignments are written to
`event_memberships_v1` with an explicit assignment version and remain
`shadow_only=true` until the M3 read switch.

## Invariants

1. A canonical Event ID is never regenerated because title, key, members, or
   lifecycle state changed.
2. Every retired key/ID/URL resolves through one alias hop to a canonical Event.
   Alias chains are rejected.
3. Merge and split never delete the input operation history.
4. v0 membership remains readable throughout expand, backfill, dual write,
   verify, and shadow phases.
5. Personal state and feedback are keyed by canonical Event ID. During a merge,
   state is copied to the canonical output with the original record retained
   until retention expiry. During a split, ambiguous state is not guessed; it
   is queued for explicit product policy or user confirmation.
6. Restricted content is referenced by ID only. Migration logs and checksums
   never copy full body text.

## Phases

### 1. Expand

Migration `20260723_0034` adds `event_aliases`, `event_operations`, and
`event_memberships_v1`. It does not alter Today queries.

### 2. Backfill

Backfill is ordered by `(created_at, event_id)` and stores a checkpoint after
each bounded batch. Each batch records:

- input row count;
- inserted/unchanged/conflict counts;
- SHA-256 checksum over stable IDs and normalized membership tuples;
- last cursor;
- code and assignment version.

Re-running a batch is idempotent. A checksum mismatch stops the migration.

### 3. Dual write and shadow

New assignments write v0 and v1 in the same business command. A failed v1
diagnostic write cannot roll back v0, but a missing required v1 membership is
reported as a reconciliation error. Today stays on v0. Shadow reports compare
membership, canonical ID, title, and personal-state reachability.

### 4. Verify and read switch

Read switching is separately gated by `event_v1_today_read`. Before enabling:

- alias resolution has no chains or cycles;
- v0/v1 checksums reconcile within the approved exception set;
- old URLs redirect to the canonical Event;
- personal state and feedback counts reconcile;
- the Event Eval and seven-day churn/merge thresholds in the PRD pass.

Briefs reference `event_id + snapshot_version`, never a mutable key.

### 5. Contract

v0 columns/tables remain read-compatible for at least one stable release after
100% read switch. Deletion is a separate reviewed migration.

## Rollback

Disable `event_v1_today_read` and `event_v1_assignment`; keep all v1 rows,
aliases, and operation history. Resume v0 reads without copying v1 state back
over v0. If a backfill batch is corrupt, use its operation rollback payload and
checkpoint to delete only rows created by that batch, then verify the previous
checksum. Outbox, delivery, audit, aliases, and operation history are never
discarded during rollback.

## Retention

Aliases and Event operations are permanent audit records unless privacy
erasure requires anonymizing actor/metadata fields. Shadow diagnostics use the
bounded diagnostic sink and follow its disk cap. Backfill checkpoints are kept
through one stable release after contract.
