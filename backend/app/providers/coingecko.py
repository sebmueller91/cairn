from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

import httpx

from app.providers.base import FetchedPrice, ProviderError, price_from_json_float


class CoinGeckoProvider:
    """Keyless, EUR-direct (no separate FX conversion needed). Roughly
    5-15 calls/minute unauthenticated — fine at ~20 instruments/day (spec 5)."""

    name = "coingecko"
    BASE_URL = "https://api.coingecko.com/api/v3"

    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(
            timeout=10.0, headers={"User-Agent": "cairn/0.1 (self-hosted)"}
        )

    def fetch_latest(self, symbol: str) -> FetchedPrice | None:
        url = f"{self.BASE_URL}/simple/price"
        try:
            response = self._client.get(
                url, params={"ids": symbol, "vs_currencies": "eur"}
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as e:
            raise ProviderError(f"coingecko request failed for {symbol}: {e}") from e
        except ValueError as e:
            # response.json() raises json.JSONDecodeError (a ValueError
            # subclass) on a 200 that isn't actually JSON — not an
            # httpx.HTTPError, so it would otherwise escape uncaught.
            raise ProviderError(f"coingecko returned invalid JSON for {symbol}: {e}") from e

        try:
            entry = data.get(symbol)
            if not entry or "eur" not in entry:
                return None
            close = price_from_json_float(entry["eur"])
        except (AttributeError, TypeError, InvalidOperation) as e:
            raise ProviderError(f"coingecko returned an unexpected shape for {symbol}: {e}") from e
        return FetchedPrice(
            date=datetime.now(UTC).date(),
            close=close,
            # CoinGecko is EUR-only (vs_currencies=eur, hardcoded above) —
            # stamp it so the fetch job can catch a mismatch against an
            # instrument configured in another currency instead of
            # silently writing a EUR price under the wrong label.
            currency="EUR",
        )

    def fetch_history(self, symbol: str, start: date, end: date) -> list[FetchedPrice]:
        url = f"{self.BASE_URL}/coins/{symbol}/market_chart"
        try:
            response = self._client.get(
                url, params={"vs_currency": "eur", "days": "max"}
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as e:
            raise ProviderError(f"coingecko history request failed for {symbol}: {e}") from e
        except ValueError as e:
            raise ProviderError(
                f"coingecko returned invalid JSON for {symbol} history: {e}"
            ) from e

        # Keep the last point seen for each calendar day: CoinGecko returns
        # sub-daily granularity for recent history, which would otherwise
        # produce multiple price_point rows for the same (instrument, date).
        try:
            prices = data.get("prices", [])
            by_day: dict[date, Decimal] = {}
            for timestamp_ms, price in prices:
                day = datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).date()
                if start <= day <= end:
                    by_day[day] = price_from_json_float(price)
        except (AttributeError, TypeError, ValueError, InvalidOperation) as e:
            raise ProviderError(
                f"coingecko returned an unexpected shape for {symbol} history: {e}"
            ) from e
        return [FetchedPrice(date=d, close=c, currency="EUR") for d, c in sorted(by_day.items())]
