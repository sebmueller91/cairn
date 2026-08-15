from datetime import date, datetime

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

        rate = data.get("rates", {}).get("EUR")
        if rate is None:
            return None
        return FetchedPrice(
            date=datetime.strptime(data["date"], "%Y-%m-%d").date(),
            close=price_from_json_float(rate),
        )

    def fetch_history(self, symbol: str, start: date, end: date) -> list[FetchedPrice]:
        url = f"{self.BASE_URL}/{start.isoformat()}..{end.isoformat()}"
        try:
            response = self._client.get(url, params={"base": symbol, "symbols": "EUR"})
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as e:
            raise ProviderError(f"frankfurter history request failed for {symbol}: {e}") from e

        results = []
        for day_str, rates in data.get("rates", {}).items():
            if "EUR" not in rates:
                continue
            results.append(
                FetchedPrice(
                    date=datetime.strptime(day_str, "%Y-%m-%d").date(),
                    close=price_from_json_float(rates["EUR"]),
                )
            )
        return sorted(results, key=lambda p: p.date)
