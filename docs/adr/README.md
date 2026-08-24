# Architecture decision records

One file per decision: `NNNN-short-title.md`, numbered in the order taken.

An ADR is not documentation of what was built — it is a record of *why* one
option won over the others, written at the moment the decision was made. Its
value shows up in six months, when the reasoning is no longer obvious and the
alternative suddenly looks attractive again.

Keep them short. A screen or less. If a decision needs three pages of
justification, it is probably two decisions.

## Template

```markdown
# NNNN — <decision in a few words>

**Status:** proposed | accepted | superseded by NNNN
**Date:** YYYY-MM-DD

## Context
What forced a choice here. Constraints that actually bind: the Pi's hardware,
single user, LAN-only, offline requirement, agent-driven writes, my ability to
review the result.

## Options considered
Two or three real candidates, with the case for each. Not a strawman lineup.

## Decision
What was chosen.

## Rationale
The trade-off that decided it. Name what was given up — a decision with no cost
usually means the alternatives were not taken seriously.

## Consequences
What this makes easy, what it makes hard, and what would have to happen to
revisit it.
```

## The record

All fifteen decisions below are **accepted** and implemented. They are kept as
written, at the moment they were taken — an ADR that gets edited to match what
was eventually built has lost the only thing it was for.

| # | Decision |
|---|---|
| [0001](0001-backend-language-and-framework.md) | Backend language and framework |
| [0002](0002-database.md) | Database |
| [0003](0003-derived-data-storage-model.md) | Storage model for derived data |
| [0004](0004-frontend-framework-charting-styling.md) | Frontend framework, charting, styling |
| [0005](0005-offline-and-caching-strategy.md) | Offline and caching strategy |
| [0006](0006-i18n-approach.md) | i18n approach |
| [0007](0007-build-and-deployment.md) | Build and deployment (macOS dev, Pi runtime) |
| [0008](0008-migrations-and-recovery.md) | Migrations and recovery from a bad one |
| [0009](0009-scheduled-jobs.md) | Scheduled jobs |
| [0010](0010-price-provider-abstraction.md) | Price provider abstraction |
| [0011](0011-authentication.md) | Authentication for a single-user LAN service |
| [0012](0012-backup-mechanics.md) | Backup mechanics and failure visibility |
| [0013](0013-test-strategy-and-golden-dataset.md) | Test strategy and golden dataset structure |
| [0014](0014-tls-single-entry-point.md) | TLS and the single entry point |
| [0015](0015-offsite-backup-transport.md) | Offsite backup transport to the NAS (closes the layer-3 gap 0012 deferred) |
