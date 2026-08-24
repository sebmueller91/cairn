# 0008 — Migrations and recovery from a bad one

**Status:** accepted
**Date:** 2026-08-15

## Context
Schema changes must go through a migration tool, never hand-edited
(AGENTS.md). SQLite's `ALTER TABLE` support is limited (no `DROP COLUMN`
before 3.35, no reliable structural down-migration for most real changes),
so "just run the down-migration" is not an honest recovery story here.

## Options considered
- **Alembic, with `alembic downgrade` as the rollback path** — the default
  reflex, but unreliable on SQLite for anything beyond additive changes.
- **Alembic for forward migrations only; file-restore as the only rollback
  path** — proposed here.

## Decision
Alembic drives all forward schema changes. Rollback of a bad migration is
**not** `alembic downgrade` — it is restoring the pre-migration `.backup`
snapshot. The deploy script wraps every migration: `sqlite3 .backup` to a
timestamped `pre-migration/` file → `PRAGMA integrity_check` on that backup →
only then `alembic upgrade head`. If the migration or the app fails
afterward, recovery is "stop the container, copy the pre-migration file back
over `cairn.db`, restart" — documented and rehearsed in
`docs/disaster-recovery.md` alongside the backup restore procedure it's
really a variant of.

## Rationale
Pretending SQLite down-migrations are a reliable safety net is worse than not
having one — it invites trusting a rollback path that will fail exactly when
needed, on a structural change. A guaranteed pre-migration file copy is
boring, cheap (the whole DB is small), and actually works every time,
independent of what the migration did.

## Consequences
Makes easy: recovery from a bad migration is identical muscle memory to
restoring from any other backup — one procedure to rehearse, not two. Makes
hard: no partial rollback of *just* the schema change while keeping
post-migration data writes — accepted, because at single-user scale a
migration failure is caught within minutes, not after a day of writes.
