"""House index-tracking valuation (spec 3.4):
house_value(t) = anchor_value * index(t) / index(anchor_date)

The index series identifier (national / state / district type) is one
config line spec itself leaves open ("pick it with the agent on the first
fetch") — stored as `instrument.valuation_config_json["index_series"]`,
not hardcoded here.
"""

from datetime import date
from decimal import Decimal


def _carry_forward(series: list[tuple[date, Decimal]], as_of: date) -> Decimal | None:
    """Latest index value at or before `as_of`. This is what makes "if the
    index fetch fails, the last known value is held" true for free: no
    special-casing a stalled fetch job, the lookup just keeps returning
    the same most-recent point until a newer one arrives."""
    value = None
    for d, v in series:
        if d > as_of:
            break
        value = v
    return value


def house_value(
    anchor_value_eur: Decimal,
    anchor_date: date,
    as_of: date,
    index_series: list[tuple[date, Decimal]],
) -> Decimal:
    """Falls back to the flat anchor value if there's no index data at
    all yet (spec doesn't mandate an index — it's the automatic default,
    not a hard requirement to have one configured)."""
    if not index_series:
        return anchor_value_eur

    index_at_anchor = _carry_forward(index_series, anchor_date)
    index_at_asof = _carry_forward(index_series, as_of)
    if not index_at_anchor or not index_at_asof:
        return anchor_value_eur

    return anchor_value_eur * index_at_asof / index_at_anchor
