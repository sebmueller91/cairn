# 0002 — Database

**Status:** accepted
**Date:** 2026-08-15

## Context
Single writer, single user, a few thousand transactions over a decade, ~20
instruments, daily snapshots charted on a Pi. Backup simplicity and query
speed on modest hardware both matter more than concurrency, which doesn't
exist here.

## Options considered
- **SQLite (WAL mode)** — spec's choice.
- **Postgres** — the default "real database" reflex.

## Decision
SQLite in WAL mode, agreeing with the spec.

## Rationale
There is no concurrent-writer scenario to design for — one agent process and
occasionally one browser tab. Postgres would add a second container, its own
memory floor (noticeable on 8GB shared with everything else), its own upgrade
and backup story (`pg_dump`/PITR/replication concepts that don't apply at
single-user scale), for zero benefit this workload needs. Backup for SQLite
is `.backup` to a file, full stop — see ADR 0012. Query speed: `daily_snapshot`
over 10 years across ~50 scope combinations is on the order of 200–400K rows
with a `(date, scope_type, scope_id)` primary key — sub-millisecond range
scans even on SD-card-class storage, let alone once the data directory moves
to an SSD (see the storage note in the covering plan).

## Consequences
Makes easy: backup is one file, no separate DB process to monitor, restore is
"copy the file back." Makes hard: no read replicas or point-in-time recovery
beyond nightly backups — accepted, since RPO of "up to 24h" is fine for a net
worth tracker, not a transaction ledger with real-time stakes. Revisit if
multi-user ever becomes a real requirement (explicitly out of scope) — that's
the actual Postgres trigger, not data volume.
