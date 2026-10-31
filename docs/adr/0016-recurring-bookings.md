# 0016 — Recurring bookings for savings plans and loan instalments

**Status:** accepted
**Date:** 2026-10-31

## Context
Savings plans and the mortgage instalment are the bulk of the ledger's
monthly movement, and they are entirely predictable. Today each execution
waits until someone books it from a statement, so the ledger is routinely
a month or two behind for no information-theoretic reason: positions,
contributions and net worth are understated in the meantime.

Ledger-first (spec 1) rules out writing balances directly, and the
non-goals rule out pulling executions from the broker. What remains is
booking the expected execution as a transaction — clearly marked as an
estimate — and letting the statement confirm or correct it.

## Options considered
- **Keep booking by hand or by agent from statements.** Correct, but the
  lag is the problem being solved.
- **An LLM agent that books the plans on a schedule.** Re-derives a fixed
  rule every month, costs money every month, and can get it wrong. A
  deterministic rule is cheaper and cannot misread itself.
- **Standing rules evaluated by an in-process job** — chosen.

## Decision
- A `recurring_booking` table holds rules: type (`BUY` or `LOAN_PAYMENT`),
  account, instrument, gross amount, fees, `day_of_month` (1–31 from the
  start, clamped to short months; −1…−28 back from the end, −2 = second last
  day), `shift_to_business_day`, quantity decimals, start/end date, active
  flag. CRUD at
  `/api/recurring-bookings`, `POST /api/recurring-bookings/run[?dry_run=true]`
  runs the job on demand.
- An occurrence is due on its nominal day, executed on the **next German
  business day** on or after it (Mon–Fri minus the nine nationwide public
  holidays; `app/business_days.py`). That may roll into the next month.
  A rule can turn the shift off and book on the calendar day as is. The
  mortgage instalment does: the bank debits it at month end, moving *back*
  to an earlier business day when the last day is not one. Rather than
  model that, the rule books on the second last day, unshifted — close
  enough for a record that changes no number.
- The job runs at **22:45 Europe/Berlin** — after the 22:30 price fetch, so a
  `BUY` prices itself from that day's close (`price_mode: auto`), and before
  the 23:00 snapshot rebuild, which then includes it.
- Every booking is an ordinary txn written through the same validation as
  `POST /api/transactions`, `provisional = true`, `source = import`,
  `external_id = recurring-<rule id>-<YYYY-MM>`, one import batch per run.
  `BUY` quantity = (amount − fees) / price, cut (not rounded) to the rule's
  decimals. `LOAN_PAYMENT` takes the loan's `monthly_payment` unless the rule
  names an amount.
- `booked_through` on the rule, not the presence of a txn, decides what has
  been handled. A booking deleted because that month really did not execute
  stays deleted.
- A failing occurrence (no price yet, …) stops that rule for the run without
  advancing it; the next run retries. Missed nights are caught up.

## Consequences
- The statement step changes from *booking* to *confirming*: patch the real
  quantity, price and fees onto the provisional row and clear `provisional`.
  A provisional row that is never confirmed stays visibly an estimate.
- `LOAN_PAYMENT` rows remain record-keeping only (3.5): the loan balance
  still comes from the amortisation schedule, so these rows add a visible
  trail without changing a single number. Extra repayments are still booked
  by hand.
- State holidays and exchange-only closures (24/31 December) are not
  modelled. An execution a day off is corrected by the statement; modelling
  each broker's calendar is not worth it.
- Booking estimates is a new kind of write the app makes on its own. It
  never moves money and touches nothing but the ledger, so the security
  stance of AGENTS.md is unchanged.
