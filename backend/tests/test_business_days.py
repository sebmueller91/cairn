from datetime import date

import pytest

from app.business_days import (
    easter_sunday,
    is_business_day,
    next_business_day,
    public_holidays,
)


@pytest.mark.parametrize(
    "year, expected",
    [
        (2019, date(2019, 4, 21)),
        (2024, date(2024, 3, 31)),
        (2025, date(2025, 4, 20)),
        (2026, date(2026, 4, 5)),
        (2038, date(2038, 4, 25)),  # the latest possible date class
    ],
)
def test_easter_sunday(year, expected):
    assert easter_sunday(year) == expected


def test_nationwide_holidays_2025():
    assert public_holidays(2025) == {
        date(2025, 1, 1),
        date(2025, 4, 18),  # Good Friday
        date(2025, 4, 21),  # Easter Monday
        date(2025, 5, 1),
        date(2025, 5, 29),  # Ascension
        date(2025, 6, 9),  # Whit Monday
        date(2025, 10, 3),
        date(2025, 12, 25),
        date(2025, 12, 26),
    }


def test_state_holidays_and_exchange_closures_are_business_days():
    assert is_business_day(date(2025, 1, 6))  # Epiphany, some states only
    assert is_business_day(date(2025, 12, 24))  # exchange closed, not a holiday


def test_next_business_day():
    assert next_business_day(date(2025, 6, 4)) == date(2025, 6, 4)  # plain Wednesday
    assert next_business_day(date(2025, 5, 31)) == date(2025, 6, 2)  # Saturday
    assert next_business_day(date(2025, 10, 3)) == date(2025, 10, 6)  # Friday holiday
    # Christmas on a Friday, then a weekend: four days later
    assert next_business_day(date(2026, 12, 25)) == date(2026, 12, 28)
    # Good Friday through Easter Monday
    assert next_business_day(date(2025, 4, 18)) == date(2025, 4, 22)
