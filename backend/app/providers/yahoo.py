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
        except ValueError as e:
            # response.json() raises json.JSONDecodeError (a ValueError
            # subclass) on a 200 that isn't actually JSON — e.g. an HTML
            # rate-limit or consent page. That's not an httpx.HTTPError, so
            # it would otherwise escape uncaught.
            raise ProviderError(f"yahoo returned invalid JSON for {symbol}: {e}") from e

        try:
            result = data.get("chart", {}).get("result")
        except AttributeError as e:
            raise ProviderError(f"yahoo returned an unexpected shape for {symbol}: {e}") from e
        if not result:
            return {}
        return result[0]

    def fetch_latest(self, symbol: str) -> FetchedPrice | None:
        chart = self._fetch_chart(symbol, {"range": "5d", "interval": "1d"})
        if not chart:
            return None
        try:
            timestamps = chart.get("timestamp") or []
            # `.get("quote", [{}])` only supplies the fallback when the key
            # is ABSENT. Yahoo returns "quote": [] for a delisted or
            # unknown symbol, and [][0] raises IndexError. `or [{}]`
            # catches both "missing" and "present but empty".
            quote_list = chart.get("indicators", {}).get("quote") or [{}]
            closes = quote_list[0].get("close") or []
        except (AttributeError, TypeError, IndexError) as e:
            raise ProviderError(f"yahoo returned an unexpected shape for {symbol}: {e}") from e
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
        try:
            timestamps = chart.get("timestamp") or []
            quote_list = chart.get("indicators", {}).get("quote") or [{}]
            closes = quote_list[0].get("close") or []
        except (AttributeError, TypeError, IndexError) as e:
            raise ProviderError(f"yahoo returned an unexpected shape for {symbol}: {e}") from e

        results = []
        for ts, close in zip(timestamps, closes):
            if close is None:
                continue
            day = datetime.fromtimestamp(ts, tz=UTC).date()
            if start <= day <= end:
                results.append(FetchedPrice(date=day, close=price_from_json_float(close)))
        return results
