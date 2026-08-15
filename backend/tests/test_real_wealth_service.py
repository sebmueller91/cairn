from datetime import date
from decimal import Decimal

from app.real_wealth_service import deflate_series


def test_deflate_series_hand_derived_20_percent_cumulative_inflation():
    # CPI rose 100 -> 120 (20% cumulative) between 2020 and 2024.
    cpi = [(date(2020, 1, 1), Decimal(100)), (date(2024, 1, 1), Decimal(120))]
    values = [
        (date(2020, 6, 1), Decimal(1000)),  # deflated by 2020's CPI (100)
        (date(2024, 6, 1), Decimal(1200)),  # deflated by 2024's CPI (120) -> unchanged
    ]
    result = deflate_series(values, cpi)
    assert result == [
        (date(2020, 6, 1), Decimal(1200)),  # 1000 * 120/100
        (date(2024, 6, 1), Decimal(1200)),  # 1200 * 120/120
    ]


def test_deflate_series_before_first_cpi_point_is_unadjusted():
    cpi = [(date(2024, 1, 1), Decimal(120))]
    values = [(date(2020, 1, 1), Decimal(1000))]
    assert deflate_series(values, cpi) == [(date(2020, 1, 1), Decimal(1000))]


def test_deflate_series_no_cpi_data_returns_values_unchanged():
    values = [(date(2020, 1, 1), Decimal(1000))]
    assert deflate_series(values, []) is values or deflate_series(values, []) == values
