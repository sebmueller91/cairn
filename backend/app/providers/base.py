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
