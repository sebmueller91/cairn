"""Concentration and structure (spec 4.4).

Two questions the mix alone cannot answer:

- *How lopsided is this?* Two portfolios can both be "70 % equity" while
  one holds forty funds and the other holds two, and every allocation
  view in this app renders those identically. Top-N share, the
  Herfindahl index and the largest single weight are the three figures
  that separate them.
- *What is it made of along an axis other than asset class?* Currency and
  liquidity tier are recorded on `instrument` (spec 2.2) and, until this
  module, aggregated nowhere — so "how much of this is really dollar
  risk" and "how much could I turn into cash this month" had no answer
  even though the data was sitting there.

The pure functions below take plain values so the arithmetic is testable
without a database; the DB-facing half lives in
`routers/concentration.py` and `routers/allocation.py`.

One limitation worth stating outright, because the number looks like it
already accounts for it and does not: concentration here is measured per
*instrument*, not through funds to their constituents. `etf_composition`
stores region and sector percentages (see look_through_service), not
individual holdings, so two ETFs that overlap heavily still count as two
independent positions. Making this true look-through would need
constituent data entered per fund, which is a far larger commitment than
this view. The UI says so where the numbers are shown.
"""

from decimal import Decimal

# Squared *percentage* shares, so the scale runs 0–10000 the way every
# published HHI does (10 equal holdings = 1000, one holding = 10000).
# Using fractions instead would give 0–1 and quietly break comparison
# against any external reference the reader might have in mind.
_HHI_SCALE = Decimal(100)


def _shares(values: list[Decimal]) -> list[Decimal] | None:
    """Each value as a fraction of the total, or None when there is no
    positive total to take a share of.

    None rather than zeros throughout: a share of nothing is undefined,
    and every caller here would otherwise report the *least* concentrated
    reading on its scale for an empty portfolio — rendering "no holdings"
    as "perfectly diversified".
    """
    positives = [v for v in values if v > 0]
    total = sum(positives, Decimal(0))
    if not positives or total <= 0:
        return None
    return [v / total for v in positives]


def herfindahl_index(values: list[Decimal]) -> float | None:
    """Sum of squared percentage weights, 0–10000.

    Reacts to the whole distribution rather than to a top slice, which is
    what makes it worth having alongside `top_n_share`: thirty holdings
    where one is 60 % of the money scores badly here and looks unremarkable
    in a top-10 figure.
    """
    shares = _shares(values)
    if shares is None:
        return None
    return float(sum((s * _HHI_SCALE) ** 2 for s in shares))


def effective_holdings(values: list[Decimal]) -> float | None:
    """10000 / HHI — the same information as the index, in a unit anyone
    can read. Ten equal holdings give exactly 10.0; twenty holdings where
    one dominates give something close to 1."""
    hhi = herfindahl_index(values)
    if hhi is None or hhi == 0:
        return None
    return 10000.0 / hhi


def top_n_share(values: list[Decimal], n: int) -> float | None:
    """Combined share of the `n` largest holdings, 0–1. Asking for more
    than exist is not an error — it just returns everything."""
    shares = _shares(values)
    if shares is None:
        return None
    return float(sum(sorted(shares, reverse=True)[:n], Decimal(0)))


def largest_share(values: list[Decimal]) -> float | None:
    """The biggest single weight, 0–1 — the "how exposed am I to one bad
    day" figure."""
    return top_n_share(values, 1)
