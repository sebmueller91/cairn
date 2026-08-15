import csv
import io
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import httpx

from app.providers.base import FetchedPrice, ProviderError


class StooqProvider:
    """Keyless CSV endpoints. Covers ETFs/shares, gold/silver spot
    (`xauusd`/`xagusd`), and full daily history for backfill (spec 5)."""

    name = "stooq"

    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(
            timeout=10.0, headers={"User-Agent": "cairn/0.1 (self-hosted)"}
        )

    def fetch_latest(self, symbol: str) -> FetchedPrice | None:
        url = f"https://stooq.com/q/l/?s={symbol}&f=sd2t2ohlcv&h&e=csv"
        try:
            response = self._client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise ProviderError(f"stooq request failed for {symbol}: {e}") from e

        rows = list(csv.DictReader(io.StringIO(response.text)))
        if not rows:
            return None
        row = rows[0]
        close_raw = row.get("Close", "N/D")
        date_raw = row.get("Date", "N/D")
        if close_raw in ("N/D", "", None) or date_raw in ("N/D", "", None):
            return None
        try:
            return FetchedPrice(
                date=datetime.strptime(date_raw, "%Y-%m-%d").date(),
                close=Decimal(close_raw),
            )
        except (InvalidOperation, ValueError) as e:
            raise ProviderError(f"stooq returned unparseable data for {symbol}: {e}") from e

    def fetch_history(self, symbol: str, start: date, end: date) -> list[FetchedPrice]:
        url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
        try:
            response = self._client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise ProviderError(f"stooq history request failed for {symbol}: {e}") from e

        results = []
        for row in csv.DictReader(io.StringIO(response.text)):
            close_raw = row.get("Close")
            date_raw = row.get("Date")
            if not close_raw or not date_raw:
                continue
            try:
                row_date = datetime.strptime(date_raw, "%Y-%m-%d").date()
            except ValueError:
                continue
            if row_date < start or row_date > end:
                continue
            try:
                results.append(FetchedPrice(date=row_date, close=Decimal(close_raw)))
            except InvalidOperation:
                continue
        return results
