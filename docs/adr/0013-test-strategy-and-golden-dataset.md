# 0013 — Test strategy and the golden dataset

**Status:** proposed
**Date:** 2026-08-15

## Context
AGENTS.md: "tests before the feature for anything that calculates... a
number I cannot trust is worse than no number." Spec chapter 10 mandates a
golden dataset covering purchase, partial sale, split, dividend, FX
purchase, in-kind transfer, and a provisional opening balance later
superseded by real history.

## Options considered
Accepting the golden-dataset requirement as-is; the decision is how it's
structured and wired into the workflow, not whether to have one.

## Decision
Test pyramid, bottom to top:
1. **Pure-function unit tests** — car depreciation formula, mortgage
   amortisation formula, FX conversion, no DB involved.
2. **Golden-dataset ledger tests** — the scenarios from spec ch. 10, loaded
   through `POST /api/transactions/bulk` itself (not a DB fixture bypassing
   the API), against a real tmp-file SQLite, asserting holdings, FIFO cost
   basis, and TWR/IRR for a known period against hand-computed expected
   values. Invented ISINs and numbers only, per AGENTS.md.
3. **API contract tests** — every write endpoint hit with intentionally
   invalid payloads, asserting the machine-readable error shape (`code`,
   `params`), not just a 4xx status.
4. **Frontend smoke tests** (from phase 3 onward) — a small Playwright
   suite: dashboard loads with cached data, one full booking flow. Not
   exhaustive — this is a personal tool, not a product with a QA team.

The golden dataset lives in `tests/golden/` as fixtures loadable both by the
test suite and by a human/agent wanting to sanity-check ledger logic after a
change — it's the regression gate, not a one-off test file.

## Rationale
Loading the golden dataset through the real bulk-import endpoint rather than
seeding the DB directly is deliberate: it exercises idempotency, dry-run,
and validation in the same pass as the ledger math, since those are exactly
the paths an agent will actually use. A fixture that bypasses the API tests
the math but not the thing that will actually go wrong in practice — a
duplicate booking or a supersede that miscounts.

## Consequences
Makes easy: any ledger-logic change gets an immediate, concrete pass/fail
against known-correct numbers — the single most effective quality measure
per spec's own framing. Makes hard: the golden dataset needs updating
whenever the transaction schema changes in a way that affects existing
scenarios — an accepted, visible cost rather than a silent one.
