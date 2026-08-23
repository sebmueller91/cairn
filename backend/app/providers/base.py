"""PriceProvider contract (ADR 0010). Every source — Stooq, CoinGecko,
Frankfurter, and whatever replaces one of them later — implements this
same shape, so swapping a broken provider is a `price_source` row change,
never a code change.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Context, Decimal, ROUND_HALF_EVEN
from typing import Protocol


@dataclass
class FetchedPrice:
    date: date
    close: Decimal
    # None for providers that don't reliably know their own currency
    # (Stooq's CSV doesn't state one, Yahoo's chart JSON doesn't either) —
    # for those, the instrument's own configured `currency` is stamped on
    # write, same as always (spec 5). Providers that DO fix a currency
    # (CoinGecko: EUR-only, Frankfurter: EUR-only) must set this so the
    # fetch job can catch a mismatch against the instrument's configured
    # currency instead of silently writing a mislabelled price — see
    # coingecko.py / frankfurter.py and price_fetch_service.py.
    currency: str | None = None


class PriceProvider(Protocol):
    name: str

    def fetch_latest(self, symbol: str) -> FetchedPrice | None:
        """None if the provider has nothing for this symbol right now —
        the caller falls through to the next provider in priority order."""
        ...

    def fetch_history(self, symbol: str, start: date, end: date) -> list[FetchedPrice]:
        ...


class ProviderError(Exception):
    """Raised on a request/parse failure — distinct from fetch_latest
    returning None, which just means 'no data,' not 'something broke.'"""


_SIGNIFICANT_DIGITS = 9
_ROUNDING_CONTEXT = Context(prec=_SIGNIFICANT_DIGITS, rounding=ROUND_HALF_EVEN)


def price_from_json_float(value: float) -> Decimal:
    """JSON-sourced prices (Yahoo, CoinGecko, Frankfurter) come back as raw
    floats and sometimes carry binary floating-point noise (129.395
    arriving as 129.39500427246094) — found live when Quantity's
    8-decimal-place check correctly rejected one. `Decimal(str(value))`
    alone isn't enough since Python's float repr faithfully reproduces
    that noise, so it needs rounding — but rounding to a fixed number of
    *decimal places* (the previous `round(value, 6)`) is wrong: it
    truncates a sub-cent token price (0.00000042) straight to 0.0, which
    `_is_plausible` then rejects as <= 0, silently orphaning that
    instrument's prices forever, and it throws away precision on
    large-magnitude quotes the same way. Round to significant digits
    instead — 9 is far more precise than any real price quote needs
    (comfortably absorbs the float noise above) while never flattening a
    small-magnitude price to zero. Always converts via `Decimal(str(...))`
    first, never `Decimal(value)` directly — the latter reproduces the
    float's exact binary value instead of its shortest round-tripping
    decimal string."""
    d = Decimal(str(value))
    if d == 0:
        return d
    return _ROUNDING_CONTEXT.create_decimal(d)
