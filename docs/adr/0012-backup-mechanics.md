# 0012 — Backup mechanics and failure visibility

**Status:** accepted
**Date:** 2026-08-15

## Context
The SQLite file is, per spec, "the crown jewel." The realistic threat isn't
an attacker, it's a bad migration or silent cron failure — the classic home
server failure mode is a backup job that stopped working months ago and
nobody noticed until the day it mattered.

## Options considered
Accepting spec 6.6's three-layer plan (nightly `.backup` + integrity check,
nightly logical export, offsite 3-2-1 via NAS + encrypted cloud) as
correct — no better alternative considered, this is a well-worn pattern
applied properly. Decisions worth pinning: where the job runs (resolved in
ADR 0009: host cron, not in-process) and how a silent failure surfaces.

## Decision
Three layers per spec 6.6, running from host cron per ADR 0009. Each backup
run writes its own result (timestamp, success/failure, integrity-check
result) to a small status file the API reads for `/api/health`; the data
quality panel warns when the last successful backup exceeds 48h, per spec.
**Deferred, not decided:** active push notification on backup failure (e.g.
self-hosted ntfy) was considered and set aside for now — it adds an
internet-egress point that sits awkwardly next to the "outbound limited to
price source domains" security rule (spec 6.4), for a benefit (catching a
failure faster than the next dashboard visit) that's marginal at
single-user, checked-almost-daily-anyway scale. Worth revisiting once the
dashboard-check habit proves unreliable in practice, not before.

## Rationale
The dashboard-visibility approach matches the spec's own framing: the
failure mode is silence, and the fix is making silence visible the next time
anyone looks, not building an alerting pipeline for a home project. Pinning
the "deferred, not decided" note explicitly here so it doesn't get quietly
lost — this is exactly the kind of nice-to-have that's easy to bolt on later
without disturbing anything already built.

## Consequences
Makes easy: backup health is just another `/api/health` field, no new
infra. Makes hard: a failure is only noticed on next dashboard visit, not
the moment it happens — accepted for now, logged as the one thing to
reconsider if it ever bites.
