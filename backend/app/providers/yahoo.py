from datetime import UTC, date, datetime, timedelta

import httpx

from app.providers.base import FetchedPrice, ProviderError, price_from_json_float


class YahooFinanceProvider:
    """Unofficial, undocumented, keyless — spec 5's own named fallback for
    ETFs/shares once Stooq stopped serving plain HTTP clients (it now
    gates its CSV endpoints behind a JS proof-of-work challenge). Being
    unofficial, this can break the same way someday; it's a fallback for
    a reason, not a foundation."""

    name = "yahoo"
    BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart"

    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(
            timeout=10.0, headers={"User-Agent": "Mozilla/5.0 (cairn/0.1 self-hosted)"}
        )

    def _fetch_chart(self, symbol: str, params: dict) -> dict:
        try:
            response = self._client.get(f"{self.BASE_URL}/{symbol}", params=params)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as e:
            raise ProviderError(f"yahoo request failed for {symbol}: {e}") from e

        result = data.get("chart", {}).get("result")
        if not result:
            return {}
        return result[0]

    def fetch_latest(self, symbol: str) -> FetchedPrice | None:
        chart = self._fetch_chart(symbol, {"range": "5d", "interval": "1d"})
        if not chart:
            return None
        timestamps = chart.get("timestamp") or []
        closes = chart.get("indicators", {}).get("quote", [{}])[0].get("close") or []
        for ts, close in reversed(list(zip(timestamps, closes))):
            if close is None:
                continue
            return FetchedPrice(
                date=datetime.fromtimestamp(ts, tz=UTC).date(),
                close=price_from_json_float(close),
            )
        return None

    def fetch_history(self, symbol: str, start: date, end: date) -> list[FetchedPrice]:
        period1 = int(datetime.combine(start, datetime.min.time(), tzinfo=UTC).timestamp())
        period2 = int(
            (datetime.combine(end, datetime.min.time(), tzinfo=UTC) + timedelta(days=1)).timestamp()
        )
        chart = self._fetch_chart(
            symbol, {"period1": period1, "period2": period2, "interval": "1d"}
        )
        if not chart:
            return []
        timestamps = chart.get("timestamp") or []
        closes = chart.get("indicators", {}).get("quote", [{}])[0].get("close") or []

        results = []
        for ts, close in zip(timestamps, closes):
            if close is None:
                continue
            day = datetime.fromtimestamp(ts, tz=UTC).date()
            if start <= day <= end:
                results.append(FetchedPrice(date=day, close=price_from_json_float(close)))
        return results
