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

## Open decisions

Listed in the plan-mode brief; expected to become ADRs 0001 onwards:

1. Backend language and framework
2. Database
3. Storage model for derived data
4. Frontend framework, charting, styling
5. Offline and caching strategy
6. i18n approach
7. Build and deployment (development on macOS, operation on a Pi)
8. Migrations and recovery from a bad one
9. Scheduled jobs
10. Price provider abstraction
11. Authentication for a single-user LAN service
12. Backup mechanics and failure visibility
13. Test strategy and the structure of the golden dataset
