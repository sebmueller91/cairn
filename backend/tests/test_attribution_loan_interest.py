"""Reproduction for attribution_service.py's sign-flipped loan interest
(bug 4). Invented figures only, per AGENTS.md.

`_loan_interest` used to compute `payments_paid - principal_reduction`,
summing `payments_paid` from LOAN_PAYMENT ledger rows. But txn_service.py
documents those as optional record-keeping -- "the loan balance itself
comes from loan_service's amortization model, not from summing these" --
so the normal state is *zero* such rows. With no LOAN_PAYMENT rows,
`payments_paid` was 0, so `_loan_interest` returned `-principal_reduction`
-- interest with the sign flipped, reported as a gain rather than a cost.
`compute_attribution` then negates it again into `costs`, so a real cost
showed up as a *positive* costs bucket, with an offsetting phantom dumped
into the `market_gains_losses` residual.

Fixed by deriving the number of regular payments from the amortisation
model itself (`loan_service.periods_elapsed`) instead of the ledger, so
it's correct whether or not LOAN_PAYMENT rows exist.
"""

from datetime import date
from decimal import Decimal


def _make_loan(client, auth_headers, **overrides):
    loan_account = client.post(
        "/api/accounts",
        json={"name": "Mortgage Test", "type": "LOAN", "currency": "EUR"},
        headers=auth_headers,
    ).json()
    payload = dict(
        account_id=loan_account["id"],
        principal="100000.00",
        rate_pct="6.0",
        start_date="2024-01-01",
        monthly_payment="1000.00",
    )
    payload.update(overrides)
    loan = client.post("/api/loans", json=payload, headers=auth_headers).json()
    return loan_account, loan


def test_loan_interest_is_a_cost_even_with_no_loan_payment_rows(
    client, auth_headers, db_session
):
    """The exact reproduction from the bug report: loan 100000.00 @ 6%,
    payment 1000.00/month, no LOAN_PAYMENT transactions booked at all
    (the normal, expected state per txn_service.py). One month elapses:
    interest = 500.00 (100000 * 6%/12), which must show up as a -500.00
    cost, not a +500.00 gain."""
    from app.attribution_service import compute_attribution
    from app.database import SessionLocal

    _make_loan(client, auth_headers)

    db = SessionLocal()
    try:
        result = compute_attribution(db, date(2024, 1, 1), date(2024, 2, 1))
    finally:
        db.close()

    assert result.costs == Decimal("-500.00")

    # The waterfall's sum invariant must still hold (market_gains_losses
    # is always a residual, by construction) -- this doesn't prove
    # correctness on its own, but a broken invariant would prove a bug.
    named_sum = (
        result.deposits_withdrawals
        + result.income
        + result.costs
        + result.valuation_adjustments
        + result.fx_effect
        + result.market_gains_losses
    )
    assert named_sum == result.end_value - result.start_value


def test_loan_interest_is_unaffected_by_optional_loan_payment_rows(
    client, auth_headers, db_session
):
    """Booking a LOAN_PAYMENT transaction is optional record-keeping
    (txn_service.py) and must not change the computed interest -- it's
    derived purely from the amortisation model, not summed from the
    ledger. Same loan/period as above; interest must still read -500.00
    with a LOAN_PAYMENT row present."""
    from app.attribution_service import compute_attribution
    from app.database import SessionLocal

    loan_account, _ = _make_loan(client, auth_headers)
    client.post(
        "/api/transactions",
        json={
            "external_id": "attr-loan-payment-1", "date": "2024-01-20",
            "type": "LOAN_PAYMENT", "account_id": loan_account["id"],
            "amount": "1000.00", "currency": "EUR",
        },
        headers=auth_headers,
    )

    db = SessionLocal()
    try:
        result = compute_attribution(db, date(2024, 1, 1), date(2024, 2, 1))
    finally:
        db.close()

    assert result.costs == Decimal("-500.00")


def test_loan_interest_over_two_months_accumulates(client, auth_headers, db_session):
    """A second month elapses on the now-slightly-smaller balance:
    interest = 99500.00 * 6%/12 = 497.50."""
    from app.attribution_service import compute_attribution
    from app.database import SessionLocal

    _make_loan(client, auth_headers)

    db = SessionLocal()
    try:
        result = compute_attribution(db, date(2024, 2, 1), date(2024, 3, 1))
    finally:
        db.close()

    assert result.costs == Decimal("-497.50")
