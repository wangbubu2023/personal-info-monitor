# Canonical Persistence Contract

This contract defines domain-visible persistence behavior. PostgreSQL is the
concurrency and transaction reference; SQLite is the Local profile dialect and
may serialize writes, but it must not change the result seen by repositories.

## Required behavior

- IDs are opaque strings. Repositories never depend on database-generated UUID
  ordering.
- Times are stored as UTC-naive values at the current application boundary and
  compared at second-or-better precision.
- JSON objects round-trip with JSON `null` distinct from a missing column.
- A business idempotency key is protected by a database unique constraint.
  Conflict returns the existing business object; it never creates a second
  side effect.
- Lease completion and heartbeat are compare-and-swap operations over
  `(id, locked_by, lease_token)`. A zero-row update is a normal ownership
  conflict, not success.
- A failed transaction is rolled back before the session is reused.
- Stable pagination orders by `(sort_value, opaque_id)` and the cursor carries
  both fields. Offset-only pagination is not a repository contract.
- Dialect-specific SQL stays inside an adapter. Domain code cannot depend on
  SQLite `INSERT OR REPLACE`, PostgreSQL advisory locks, JSON operators, or
  implicit NULL ordering.

## CI profile

`tests/test_persistence_contract.py` always runs against SQLite. When
`PIM_TEST_POSTGRES_URL` is configured, the same test also runs against
PostgreSQL and covers unique conflicts, rollback, CAS, JSON/NULL/time
round-trips, stable ordering, and cursor pagination.

The contract is intentionally narrower than the Server profile. Connection
pool sizing, PostgreSQL backup/restore, data copy, and production cutover live
in the Server migration runbook.
