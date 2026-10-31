"""German business days for recurring bookings: Monday to Friday, minus
the nationwide public holidays (gesetzliche Feiertage in every Land).

Deliberately nationwide only. State holidays (Epiphany, Corpus Christi,
Assumption, Reformation Day, All Saints', ...) depend on where the
*broker or bank* sits, not where the user lives, and a savings plan that
executes a day earlier or later than modelled is corrected by the
statement anyway. Exchange-only closing days (24 and 31 December) are not
public holidays and are left out for the same reason.

Computed rather than taken from a dependency: nine dates, one of which
(Easter) needs a formula, is not worth a package.
"""

from datetime import date, timedelta


def easter_sunday(year: int) -> date:
    """Gregorian Easter Sunday (the anonymous Gregorian algorithm,
    a.k.a. Meeus/Jones/Butcher)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741 — the algorithm's own name
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def public_holidays(year: int) -> set[date]:
    easter = easter_sunday(year)
    return {
        date(year, 1, 1),  # Neujahr
        easter - timedelta(days=2),  # Karfreitag
        easter + timedelta(days=1),  # Ostermontag
        date(year, 5, 1),  # Tag der Arbeit
        easter + timedelta(days=39),  # Christi Himmelfahrt
        easter + timedelta(days=50),  # Pfingstmontag
        date(year, 10, 3),  # Tag der Deutschen Einheit
        date(year, 12, 25),  # 1. Weihnachtstag
        date(year, 12, 26),  # 2. Weihnachtstag
    }


def is_business_day(d: date) -> bool:
    return d.weekday() < 5 and d not in public_holidays(d.year)


def next_business_day(d: date) -> date:
    """`d` itself if it is a business day, otherwise the first one after
    it — which may fall into the next month (a payment due on Saturday
    the 31st is executed on Monday the 2nd)."""
    while not is_business_day(d):
        d += timedelta(days=1)
    return d
