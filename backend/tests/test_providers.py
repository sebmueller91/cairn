"""Provider adapters tested against canned responses (httpx.MockTransport)
— no real network in the test suite. Live connectivity is verified
separately against the actual deployment, not here."""

from datetime import date
from decimal import Decimal

import httpx

from app.providers.coingecko import CoinGeckoProvider
from app.providers.frankfurter import FrankfurterProvider
from app.providers.stooq import StooqProvider
from app.providers.yahoo import YahooFinanceProvider


def _client_with(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_stooq_fetch_latest_parses_csv():
    def handler(request):
        return httpx.Response(
            200,
            text="Symbol,Date,Time,Open,High,Low,Close,Volume\n"
            "EUNL.DE,2024-01-15,17:35:00,90.5,91.2,90.3,91.05,12345\n",
        )

    provider = StooqProvider(client=_client_with(handler))
    result = provider.fetch_latest("EUNL.DE")
    assert result.date == date(2024, 1, 15)
    assert result.close == Decimal("91.05")


def test_stooq_fetch_latest_returns_none_for_no_data():
    def handler(request):
        return httpx.Response(
            200, text="Symbol,Date,Time,Open,High,Low,Close,Volume\nXX,N/D,N/D,N/D,N/D,N/D,N/D,N/D\n"
        )

    provider = StooqProvider(client=_client_with(handler))
    assert provider.fetch_latest("XX") is None


def test_stooq_fetch_history_filters_date_range():
    def handler(request):
        return httpx.Response(
            200,
            text="Date,Open,High,Low,Close,Volume\n"
            "2024-01-01,80,81,79,80.5,1000\n"
            "2024-01-02,80.5,82,80,81.5,1000\n"
            "2024-06-01,90,91,89,90.5,1000\n",
        )

    provider = StooqProvider(client=_client_with(handler))
    result = provider.fetch_history("EUNL.DE", date(2024, 1, 1), date(2024, 1, 2))
    assert len(result) == 2
    assert result[0].close == Decimal("80.5")
    assert result[1].close == Decimal("81.5")


def test_coingecko_fetch_latest():
    def handler(request):
        return httpx.Response(200, json={"bitcoin": {"eur": 45000.12}})

    provider = CoinGeckoProvider(client=_client_with(handler))
    result = provider.fetch_latest("bitcoin")
    assert result.close == Decimal("45000.12")


def test_coingecko_fetch_history_dedupes_to_one_point_per_day():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "prices": [
                    [1704067200000, 42000.0],  # 2024-01-01 00:00 UTC
                    [1704110400000, 42500.0],  # 2024-01-01 12:00 UTC
                    [1704153600000, 43000.0],  # 2024-01-02 00:00 UTC
                ]
            },
        )

    provider = CoinGeckoProvider(client=_client_with(handler))
    result = provider.fetch_history("bitcoin", date(2024, 1, 1), date(2024, 1, 2))
    assert len(result) == 2
    assert result[0].date == date(2024, 1, 1)
    assert result[0].close == Decimal("42500.0")  # last point of that day wins


def test_frankfurter_fetch_latest():
    def handler(request):
        return httpx.Response(
            200, json={"amount": 1, "base": "USD", "date": "2024-01-15", "rates": {"EUR": 0.92}}
        )

    provider = FrankfurterProvider(client=_client_with(handler))
    result = provider.fetch_latest("USD")
    assert result.date == date(2024, 1, 15)
    assert result.close == Decimal("0.92")


def test_yahoo_fetch_latest_takes_last_non_null_close():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "chart": {
                    "result": [
                        {
                            "timestamp": [1704067200, 1704153600, 1704240000],
                            "indicators": {
                                "quote": [{"close": [90.5, None, 91.2]}]
                            },
                        }
                    ]
                }
            },
        )

    provider = YahooFinanceProvider(client=_client_with(handler))
    result = provider.fetch_latest("EUNL.DE")
    assert result.date == date(2024, 1, 3)
    assert result.close == Decimal("91.2")


def test_yahoo_absorbs_float_noise_from_json(monkeypatch):
    """Real bug found live: Yahoo's JSON returned 129.39500427246094 for a
    price that should read 129.395 — Quantity's 8dp check correctly
    rejected it before the fix. Rounding to 6dp in the adapter absorbs
    the noise while staying far more precise than any real quote needs."""

    def handler(request):
        return httpx.Response(
            200,
            json={
                "chart": {
                    "result": [
                        {
                            "timestamp": [1704067200],
                            "indicators": {"quote": [{"close": [129.39500427246094]}]},
                        }
                    ]
                }
            },
        )

    provider = YahooFinanceProvider(client=_client_with(handler))
    result = provider.fetch_latest("EUNL.DE")
    # Rounded to 6dp, not fully clean back to 129.395 — but well under
    # Quantity's 8dp limit and immaterial for a price (ADR-level choice:
    # consistent precision across providers beats chasing an unknowable
    # "true" precision from noisy source data).
    assert result.close == Decimal("129.395004")


def test_yahoo_fetch_latest_returns_none_on_empty_result():
    def handler(request):
        return httpx.Response(200, json={"chart": {"result": None}})

    provider = YahooFinanceProvider(client=_client_with(handler))
    assert provider.fetch_latest("BOGUS") is None


def test_yahoo_fetch_history_filters_range_and_skips_nulls():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "chart": {
                    "result": [
                        {
                            "timestamp": [1704067200, 1704153600, 1706745600],
                            "indicators": {
                                "quote": [{"close": [90.5, None, 95.0]}]
                            },
                        }
                    ]
                }
            },
        )

    provider = YahooFinanceProvider(client=_client_with(handler))
    result = provider.fetch_history("EUNL.DE", date(2024, 1, 1), date(2024, 1, 3))
    assert len(result) == 1
    assert result[0].close == Decimal("90.5")


def test_frankfurter_fetch_history():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "rates": {
                    "2024-01-01": {"EUR": 0.91},
                    "2024-01-02": {"EUR": 0.915},
                }
            },
        )

    provider = FrankfurterProvider(client=_client_with(handler))
    result = provider.fetch_history("USD", date(2024, 1, 1), date(2024, 1, 2))
    assert len(result) == 2
    assert result[0].date == date(2024, 1, 1)
    assert result[0].close == Decimal("0.91")
