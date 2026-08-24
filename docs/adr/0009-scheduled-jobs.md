# 0009 — Scheduled jobs

**Status:** accepted
**Date:** 2026-08-15

## Context
Three recurring jobs: price fetch (22:30 EOD), snapshot rebuild, backup.
`/api/health` must report the last successful run of each. The failure mode
to design against is a job silently stopping without anyone noticing.

## Options considered
- **Everything via in-process APScheduler inside the API container** —
  spec's proposal.
- **Everything via host cron, jobs as separate script invocations.**
- **Split: domain jobs in-process, backup via host cron** — proposed here.

## Decision
Price fetch and snapshot rebuild run in-process via APScheduler inside the
API container — they need the ORM/service layer directly and there's no
reason to shell out to a separate process for them. **Backup runs from host
cron** (or an equivalent tiny sidecar container per the spec's own compose
sketch), invoking `sqlite3 .backup` directly against the bind-mounted data
directory, independent of the API process's health.

## Rationale
The whole point of a backup is surviving the application being broken. If
backups are scheduled from inside the same container they're backing up, a
wedged or crash-looping API container silently stops producing backups at
exactly the moment backups matter most — the failure is correlated with the
thing it's supposed to protect against. Host cron (or a separate container)
has no dependency on the API process being healthy. Price fetch and snapshot
rebuild don't have this problem — if the API container is down, there's
nothing to fetch prices *for* anyway, so coupling their schedule to the
API's own liveness is fine.

## Consequences
Makes easy: backup health is genuinely independent of API health, which is
what `/api/health` reporting "last successful backup" is supposed to mean.
Makes hard: one job (backup) lives outside the app's own code and test
suite — mitigated by keeping it a short, reviewed shell script, not
application logic.
