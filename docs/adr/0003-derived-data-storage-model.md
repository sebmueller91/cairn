# 0003 — Storage model for derived data

**Status:** accepted
**Date:** 2026-08-15

## Context
Holdings, valuations and time series must never become a second source of
truth alongside the transaction ledger (AGENTS.md hard rule). But re-folding
the entire ledger on every request doesn't scale to multi-year daily charts
on a Pi. Need a model that is fast to read and trivially, provably
reconstructible.

## Options considered
- **Two layers: live aggregation for "now," a `daily_snapshot` cache table
  for history** — proposed here.
- **Everything live-computed, no snapshot table** — simplest, but spec's
  own stated reason for `daily_snapshot` (10-year charts on a Pi) rules it
  out for the historical case.
- **Event-sourced read models with incremental projections from day one** —
  more machinery than a single-user app with a few thousand events needs.

## Decision
Two layers. **Current state** (positions, holdings shown in Positions/
Dashboard "now") is computed on demand by aggregating `txn` directly — a
`GROUP BY account_id, instrument_id` over a few thousand rows, cheap enough
to never cache. **Historical state** (`daily_snapshot`) is a nightly-job
materialization, walking the ledger day by day, written as a strict cache:
`POST /api/admin/rebuild-snapshots` always produces an identical result from
`txn` + `price_point` + `fx_rate` + `valuation_anchor` + `loan` alone. Every
table that is not in that source list (`account`, `instrument`, `txn`,
`price_source`, `price_point`, `fx_rate`, `valuation_anchor`, `loan`,
`target_allocation`, `setting`, `audit_log`) is either primary data or
externally-fetched fact data, never a derived cache — everything else is
disposable and rebuildable.

Rebuilds are made cheap without weakening that guarantee via a per-account
`dirty_from` watermark: an edited transaction moves the watermark back to its
date, and the nightly job recomputes only snapshot rows from the earliest
dirty watermark forward, not the full decade. The full-rebuild endpoint
remains the ground truth and ignores watermarks entirely.

## Rationale
The alternative to "obviously reconstructible from source tables" is having
to reason about whether a cache is still correct after every ledger edit —
exactly the trust problem AGENTS.md is trying to prevent ("a number I cannot
trust is worse than no number"). The watermark is an optimization on top of
a full-rebuild guarantee, not a replacement for it, so a bug in the watermark
logic degrades to "slower," never to "wrong."

## Consequences
Makes easy: any snapshot bug is fixed by `POST /api/admin/rebuild-snapshots`,
no migration needed, no data loss possible from a snapshot-layer bug. Makes
hard: the watermark logic itself needs its own tests (a backfill touching
three accounts must dirty all three, not just one) — this is exactly the kind
of "calculation" AGENTS.md wants tested before trusted.
