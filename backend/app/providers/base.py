"""PriceProvider contract (ADR 0010). Every source — Stooq, CoinGecko,
Frankfurter, and whatever replaces one of them later — implements this
same shape, so swapping a broken provider is a `price_source` row change,
never a code change.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol


@dataclass
class FetchedPrice:
    date: date
    close: Decimal
    # No currency field: a provider doesn't reliably know it (Stooq's CSV
    # doesn't state one), and it doesn't need to — the instrument's own
    # `currency` is set once by hand when the price source is configured
    # (spec 5), and the fetch job stamps it on write.


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


def price_from_json_float(value: float) -> Decimal:
    """JSON-sourced prices (Yahoo, CoinGecko) come back as raw floats and
    sometimes carry binary floating-point noise (129.395 arriving as
    129.39500427246094) — found live when Quantity's 8-decimal-place
    check correctly rejected one. `Decimal(str(value))` alone isn't
    enough since Python's float repr faithfully reproduces that noise;
    rounding to 6dp first absorbs it while staying far more precise than
    any real price quote needs."""
    return Decimal(str(round(value, 6)))
