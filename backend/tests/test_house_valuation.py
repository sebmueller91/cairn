"""spec 3.4."""

from datetime import date
from decimal import Decimal

from app.house_valuation import house_value


def test_no_index_data_holds_the_anchor_flat():
    assert house_value(Decimal("400000"), date(2020, 1, 1), date(2026, 1, 1), []) == Decimal(
        "400000"
    )


def test_index_increase_scales_the_anchor_proportionally():
    series = [
        (date(2020, 1, 1), Decimal("100.0")),
        (date(2026, 1, 1), Decimal("120.0")),
    ]
    value = house_value(Decimal("400000"), date(2020, 1, 1), date(2026, 1, 1), series)
    assert value == Decimal("480000.0")  # +20%, matching the index


def test_stalled_fetch_holds_the_last_known_index_value():
    series = [
        (date(2020, 1, 1), Decimal("100.0")),
        (date(2024, 1, 1), Decimal("110.0")),
        # no data after 2024 -> a fetch job that stopped running
    ]
    value_2024 = house_value(Decimal("400000"), date(2020, 1, 1), date(2024, 6, 1), series)
    value_2026 = house_value(Decimal("400000"), date(2020, 1, 1), date(2026, 1, 1), series)
    assert value_2024 == value_2026  # flat, held at the last known point


def test_missing_anchor_era_data_falls_back_to_flat():
    # anchor predates the whole index series -> no valid ratio to compute
    series = [(date(2024, 1, 1), Decimal("110.0"))]
    value = house_value(Decimal("400000"), date(2020, 1, 1), date(2026, 1, 1), series)
    assert value == Decimal("400000")
