"""Bug 2 & 6 coverage: providers must raise only ProviderError for any
upstream misbehaviour (bad JSON, unexpected shape, empty arrays, missing
keys) instead of leaking IndexError/KeyError/json.JSONDecodeError, and a
provider that fixes its own currency (CoinGecko, Frankfurter: EUR-only)
must not have that price silently stamped under a mismatched instrument
currency. Also covers bug 5 (price_from_json_float rounds to significant
digits, not a fixed number of decimal places).

No real network — canned responses via httpx.MockTransport, same pattern
as test_providers.py.
"""

from datetime import date
from decimal import Decimal

import httpx
import pytest

from app.models import AssetClass, Instrument, PriceSource, ValuationMode
from app.price_fetch_service import backfill_for_instrument, fetch_latest_for_instrument
from app.providers.base import ProviderError, price_from_json_float
from app.providers.coingecko import CoinGeckoProvider
from app.providers.frankfurter import FrankfurterProvider
from app.providers.yahoo import YahooFinanceProvider


def _client_with(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


# --- Bug 2: shape/JSON failures must surface as ProviderError -------------


def test_yahoo_empty_quote_list_does_not_raise_indexerror():
    """Yahoo returns "quote": [] (not absent) for a delisted/unknown
    symbol. The old `.get("quote", [{}])[0]` default only kicks in when
    the key is missing entirely, so `[][0]` raised an uncaught IndexError
    that escaped fetch_latest_for_instrument's `except ProviderError`."""

    def handler(request):
        return httpx.Response(
            200,
            json={
                "chart": {
                    "result": [
                        {
                            "timestamp": [1704067200],
                            "indicators": {"quote": []},
                        }
                    ]
                }
            },
        )

    provider = YahooFinanceProvider(client=_client_with(handler))
    # Must not raise at all - degrades to "no data" like any other miss.
    assert provider.fetch_latest("DELISTED") is None
    assert provider.fetch_history("DELISTED", date(2024, 1, 1), date(2024, 1, 2)) == []


def test_yahoo_invalid_json_raises_provider_error():
    """A 200 carrying an HTML rate-limit/consent page instead of JSON
    raises json.JSONDecodeError from response.json(), which is NOT a
    subclass of httpx.HTTPError and used to escape the adapter entirely."""

    def handler(request):
        return httpx.Response(200, text="<html>rate limited</html>")

    provider = YahooFinanceProvider(client=_client_with(handler))
    with pytest.raises(ProviderError):
        provider.fetch_latest("EUNL.DE")


def test_coingecko_invalid_json_raises_provider_error():
    def handler(request):
        return httpx.Response(200, text="not json")

    provider = CoinGeckoProvider(client=_client_with(handler))
    with pytest.raises(ProviderError):
        provider.fetch_latest("bitcoin")


def test_frankfurter_invalid_json_raises_provider_error():
    def handler(request):
        return httpx.Response(200, text="not json")

    provider = FrankfurterProvider(client=_client_with(handler))
    with pytest.raises(ProviderError):
        provider.fetch_latest("USD")


def test_frankfurter_missing_date_key_raises_provider_error():
    """`data["date"]` on a response that has rates but no top-level
    "date" (a malformed/bot-protection body that still happens to look
    JSON-ish) used to raise an uncaught KeyError."""

    def handler(request):
        return httpx.Response(200, json={"amount": 1, "base": "USD", "rates": {"EUR": 0.9}})

    provider = FrankfurterProvider(client=_client_with(handler))
    with pytest.raises(ProviderError):
        provider.fetch_latest("USD")


def test_yahoo_missing_indicators_key_does_not_crash():
    """Belt-and-braces: an entirely different but still-200 shape (e.g. a
    Yahoo API version change) must degrade to ProviderError/None, not an
    unhandled AttributeError/TypeError."""

    def handler(request):
        return httpx.Response(200, json={"chart": {"result": [{"timestamp": [1]}]}})

    provider = YahooFinanceProvider(client=_client_with(handler))
    assert provider.fetch_latest("X") is None


# --- Bug 5: significant-digit rounding, not fixed decimal places ----------


def test_price_from_json_float_does_not_zero_out_tiny_magnitude_price():
    """round(value, 6) truncated a sub-cent token price straight to 0.0,
    which _is_plausible then rejects as <= 0 - silently orphaning that
    instrument's prices forever."""
    result = price_from_json_float(0.00000042)
    assert result > 0
    assert result == Decimal("0.00000042")


def test_price_from_json_float_absorbs_binary_float_noise():
    result = price_from_json_float(129.39500427246094)
    assert result == Decimal("129.395004")


def test_price_from_json_float_rounds_to_significant_digits_not_decimal_places():
    """The old `round(value, 6)` was absolute decimal places: a 10-digit
    value would keep all 6 decimals *and* every integer digit, i.e. more
    precision than 6dp implies for large magnitudes, while truncating
    small magnitudes to nothing (see the tiny-token test above). Rounding
    to 9 *significant* digits instead means a 9-digit value like this one
    is returned unchanged, while a 10th digit would be rounded off."""
    assert price_from_json_float(1234567.89) == Decimal("1234567.89")
    assert price_from_json_float(123456789.123) == Decimal("123456789")


# --- Bug 6: EUR-only providers must not mislabel a non-EUR instrument -----


def test_coingecko_and_frankfurter_stamp_eur_currency():
    def cg_handler(request):
        return httpx.Response(200, json={"bitcoin": {"eur": 100.0}})

    def fx_handler(request):
        return httpx.Response(
            200, json={"amount": 1, "base": "USD", "date": "2024-01-15", "rates": {"EUR": 0.9}}
        )

    cg_result = CoinGeckoProvider(client=_client_with(cg_handler)).fetch_latest("bitcoin")
    fx_result = FrankfurterProvider(client=_client_with(fx_handler)).fetch_latest("USD")
    assert cg_result.currency == "EUR"
    assert fx_result.currency == "EUR"


@pytest.fixture
def usd_instrument(db_session):
    i = Instrument(
        name="USD-denominated crypto",
        isin="XX0000000091",
        asset_class=AssetClass.EQUITY,
        valuation_mode=ValuationMode.MARKET,
        currency="USD",
        valuation_config_json="{}",
        tags_json="[]",
    )
    db_session.add(i)
    db_session.commit()
    db_session.refresh(i)
    return i


class _EurOnlyProvider:
    """Stand-in for CoinGecko/Frankfurter: always reports an EUR price,
    regardless of what currency the instrument is configured for."""

    def __init__(self, close=Decimal("100.00")):
        self._close = close

    def fetch_latest(self, symbol):
        from app.providers.base import FetchedPrice

        return FetchedPrice(date=date(2024, 6, 1), close=self._close, currency="EUR")

    def fetch_history(self, symbol, start, end):
        from app.providers.base import FetchedPrice

        return [FetchedPrice(date=start, close=self._close, currency="EUR")]


def test_fetch_latest_refuses_mismatched_currency(db_session, usd_instrument, monkeypatch):
    source = PriceSource(
        instrument_id=usd_instrument.id, provider="coingecko", provider_symbol="bitcoin", priority=0
    )
    db_session.add(source)
    db_session.commit()

    monkeypatch.setattr(
        "app.price_fetch_service.get_provider", lambda name: _EurOnlyProvider()
    )

    result = fetch_latest_for_instrument(db_session, usd_instrument)
    assert result.status == "all_sources_failed"
    assert "refusing" in source.last_error
    assert "EUR" in source.last_error
    assert "USD" in source.last_error

    # No mislabelled price_point should have been written.
    from app.models import PricePoint

    assert db_session.get(PricePoint, (usd_instrument.id, date(2024, 6, 1))) is None


def test_backfill_refuses_mismatched_currency(db_session, usd_instrument, monkeypatch):
    source = PriceSource(
        instrument_id=usd_instrument.id, provider="frankfurter", provider_symbol="bitcoin", priority=0
    )
    db_session.add(source)
    db_session.commit()

    monkeypatch.setattr(
        "app.price_fetch_service.get_provider", lambda name: _EurOnlyProvider()
    )

    result = backfill_for_instrument(
        db_session, usd_instrument, date(2024, 1, 1), date(2024, 1, 2)
    )
    assert result.status == "all_sources_failed"
    assert "refusing" in source.last_error


def test_fetch_latest_accepts_matching_currency(db_session, monkeypatch):
    """Sanity check: the mismatch guard doesn't reject a EUR provider
    price for a EUR instrument (result.currency == instrument.currency)."""
    eur_instrument = Instrument(
        name="EUR ETF",
        isin="XX0000000092",
        asset_class=AssetClass.EQUITY,
        valuation_mode=ValuationMode.MARKET,
        currency="EUR",
        valuation_config_json="{}",
        tags_json="[]",
    )
    db_session.add(eur_instrument)
    db_session.commit()
    db_session.refresh(eur_instrument)

    source = PriceSource(
        instrument_id=eur_instrument.id, provider="coingecko", provider_symbol="bitcoin", priority=0
    )
    db_session.add(source)
    db_session.commit()

    monkeypatch.setattr(
        "app.price_fetch_service.get_provider", lambda name: _EurOnlyProvider()
    )

    result = fetch_latest_for_instrument(db_session, eur_instrument)
    assert result.status == "ok"
