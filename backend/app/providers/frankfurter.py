from datetime import date, datetime
from decimal import InvalidOperation

import httpx

from app.providers.base import FetchedPrice, ProviderError, price_from_json_float


class FrankfurterProvider:
    """ECB reference rates, keyless. `symbol` here is the base currency
    (e.g. "USD") — this app always converts to EUR (docs/data-model.md),
    so `symbols=EUR` is fixed rather than a parameter.

    ECB doesn't publish rates on weekends/bank holidays, so history has
    gaps — carrying the last known rate forward is the fetch job's job,
    not this adapter's.
    """

    name = "frankfurter"
    BASE_URL = "https://api.frankfurter.dev/v1"

    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(timeout=10.0)

    def fetch_latest(self, symbol: str) -> FetchedPrice | None:
        try:
            response = self._client.get(
                f"{self.BASE_URL}/latest", params={"base": symbol, "symbols": "EUR"}
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as e:
            raise ProviderError(f"frankfurter request failed for {symbol}: {e}") from e
        except ValueError as e:
            # response.json() raises json.JSONDecodeError (a ValueError
            # subclass) on a 200 that isn't actually JSON — not an
            # httpx.HTTPError, so it would otherwise escape uncaught.
            raise ProviderError(f"frankfurter returned invalid JSON for {symbol}: {e}") from e

        try:
            rate = data.get("rates", {}).get("EUR")
            if rate is None:
                return None
            date_str = data["date"]  # can be absent on a malformed/bot-page response
            parsed_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            close = price_from_json_float(rate)
        except (AttributeError, TypeError, KeyError, ValueError, InvalidOperation) as e:
            raise ProviderError(f"frankfurter returned an unexpected shape for {symbol}: {e}") from e
        return FetchedPrice(
            date=parsed_date,
            close=close,
            # Frankfurter always converts to EUR (symbols=EUR, hardcoded
            # above) — stamp it so the fetch job can catch a mismatch
            # against an instrument configured in another currency instead
            # of silently writing a EUR price under the wrong label.
            currency="EUR",
        )

    def fetch_history(self, symbol: str, start: date, end: date) -> list[FetchedPrice]:
        url = f"{self.BASE_URL}/{start.isoformat()}..{end.isoformat()}"
        try:
            response = self._client.get(url, params={"base": symbol, "symbols": "EUR"})
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as e:
            raise ProviderError(f"frankfurter history request failed for {symbol}: {e}") from e
        except ValueError as e:
            raise ProviderError(
                f"frankfurter returned invalid JSON for {symbol} history: {e}"
            ) from e

        try:
            results = []
            for day_str, rates in data.get("rates", {}).items():
                if "EUR" not in rates:
                    continue
                results.append(
                    FetchedPrice(
                        date=datetime.strptime(day_str, "%Y-%m-%d").date(),
                        close=price_from_json_float(rates["EUR"]),
                        currency="EUR",
                    )
                )
        except (AttributeError, TypeError, ValueError, InvalidOperation) as e:
            raise ProviderError(
                f"frankfurter returned an unexpected shape for {symbol} history: {e}"
            ) from e
        return sorted(results, key=lambda p: p.date)
