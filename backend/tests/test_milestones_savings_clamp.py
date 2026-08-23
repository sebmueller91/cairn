"""trailing_12mo_savings_rate must clamp to the latest snapshotted date,
the same way contributions_service._total_on and routers/performance.py
+ routers/attribution.py already do (with an explanatory comment in each).

The nightly `rebuild_snapshots` run only catches up hours after midnight
(app.performance_query.latest_snapshot_date's own docstring). Before this
fix, an exact `DailySnapshot.date == d` miss for "today" read as
Decimal(0) cash — so a flat, unchanged 20,000 balance came out reporting
a swing to zero and a wildly negative monthly savings rate for the entire
stretch of every day before that evening's rebuild, even though nothing
happened.

Invented amounts only, per AGENTS.md.
"""

from datetime import date, timedelta
from decimal import Decimal

from app.milestones_service import trailing_12mo_savings_rate
from app.models import Account, AccountType, DailySnapshot


def test_savings_rate_clamps_to_latest_snapshot_before_nightly_rebuild(db_session):
    account = Account(name="Girokonto", type=AccountType.CASH, currency="EUR")
    db_session.add(account)
    db_session.commit()

    # The nightly rebuild's own trailing edge — the last day actually
    # snapshotted. "as_of" below stands in for "right now", a day later,
    # before tonight's rebuild has run.
    latest_snapshotted_day = date(2025, 6, 30)
    as_of = latest_snapshotted_day + timedelta(days=1)

    balance = Decimal("20000.00")
    # Both the unclamped window's start (as_of - 365, what today's buggy
    # lookup uses) and the clamped window's start (latest_snapshotted_day
    # - 365, what the fix should use) get a row — the balance never moved,
    # so both read the same flat figure either way.
    for d in (
        as_of - timedelta(days=365),
        latest_snapshotted_day - timedelta(days=365),
        latest_snapshotted_day,
    ):
        db_session.add(
            DailySnapshot(
                date=d, scope_type="cash_account", scope_id=str(account.id),
                value_eur=balance,
            )
        )
    # latest_snapshot_date() keys off scope_type="total" rows.
    db_session.add(
        DailySnapshot(
            date=latest_snapshotted_day, scope_type="total", scope_id="investable",
            value_eur=balance,
        )
    )
    db_session.commit()

    rate = trailing_12mo_savings_rate(db_session, as_of=as_of)

    # A flat, untouched balance must report zero savings, not a fabricated
    # loss from reading "today" (no row yet) as an empty account.
    assert rate == Decimal("0.00")
