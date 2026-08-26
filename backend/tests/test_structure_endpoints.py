"""The structure endpoints: /api/allocation/breakdown (spec 7.1's
`dimension` vocabulary) and /api/concentration (spec 4.4).

The load-bearing test here is that a breakdown sums to the snapshot total
for its scope. `snapshot_service` defines investable/gross/net by
*valuation mode* (MARKET + cash, plus ANCHORED/MODELED, minus loans), not
by asset class, and a breakdown that quietly used a different definition
would disagree with the net-worth figure on every other page while
looking perfectly reasonable on its own.

Invented ISINs, amounts and holdings only, per AGENTS.md.
"""

from datetime import date
from decimal import Decimal

import pytest


def _setup_mixed_portfolio(client, auth_headers, db_session):
    """One of each kind, so every scope boundary has something on both
    sides of it: two market instruments in different currencies, a cash
    account, a house (ANCHORED) and a loan against it."""
    from app.models import PricePoint, FxRate

    accounts = {}
    for name, type_, currency in [
        ("Depot", "BROKERAGE", "EUR"),
        ("Giro", "CASH", "EUR"),
        ("Haus", "REAL_ESTATE", "EUR"),
        ("Hypothek", "LOAN", "EUR"),
    ]:
        accounts[name] = client.post(
            "/api/accounts",
            json={"name": name, "type": type_, "currency": currency},
            headers=auth_headers,
        ).json()["id"]

    eur_etf = client.post(
        "/api/instruments",
        json={
            "name": "Euro ETF", "isin": "XX0000001000", "asset_class": "EQUITY",
            "valuation_mode": "MARKET", "currency": "EUR", "liquidity_tier": "T1",
        },
        headers=auth_headers,
    ).json()["id"]
    usd_etf = client.post(
        "/api/instruments",
        json={
            "name": "Dollar ETF", "isin": "XX0000001001", "asset_class": "EQUITY",
            "valuation_mode": "MARKET", "currency": "USD", "liquidity_tier": "T1",
        },
        headers=auth_headers,
    ).json()["id"]
    # No liquidity_tier at all — the unclassified case, which is the
    # normal state of this field until somebody sits down and fills it in.
    gold = client.post(
        "/api/instruments",
        json={
            "name": "Gold", "isin": "XX0000001002", "asset_class": "COMMODITY",
            "valuation_mode": "MARKET", "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]

    d = date(2024, 6, 3)
    for instrument_id, close, currency in [
        (eur_etf, "100.00", "EUR"),
        (usd_etf, "200.00", "USD"),
        (gold, "50.00", "EUR"),
    ]:
        db_session.add(
            PricePoint(
                instrument_id=instrument_id, date=d, close=Decimal(close),
                currency=currency, provider="test", quality="ok",
            )
        )
    db_session.add(FxRate(currency="USD", date=d, eur_rate=Decimal("0.90")))
    db_session.commit()

    for n, (instrument_id, qty, price, currency) in enumerate(
        [(eur_etf, "10", "100.00", "EUR"), (usd_etf, "5", "200.00", "USD"),
         (gold, "4", "50.00", "EUR")]
    ):
        client.post(
            "/api/transactions",
            json={
                "external_id": f"conc-buy-{n}", "date": "2024-06-03", "type": "BUY",
                "account_id": accounts["Depot"], "instrument_id": instrument_id,
                "quantity": qty, "price": price, "currency": currency,
            },
            headers=auth_headers,
        )

    client.post(
        "/api/transactions",
        json={
            "external_id": "conc-cash-1", "date": "2024-06-03", "type": "BALANCE_STATEMENT",
            "account_id": accounts["Giro"], "amount": "2000.00", "currency": "EUR",
        },
        headers=auth_headers,
    )
    client.post("/api/admin/rebuild-snapshots", headers=auth_headers)
    return accounts, {"eur_etf": eur_etf, "usd_etf": usd_etf, "gold": gold}


# --- the invariant --------------------------------------------------------


@pytest.mark.parametrize("scope", ["investable", "gross", "net"])
@pytest.mark.parametrize("dimension", ["asset_class", "account", "currency", "liquidity"])
def test_breakdown_sums_to_the_snapshot_total(
    client, auth_headers, db_session, scope, dimension
):
    """Every dimension is a repartition of the same money, so all of them
    must add up to the same figure — the one /api/timeseries/networth
    reports for that scope. This is the test that would catch a scope
    boundary drawn differently here than in snapshot_service.

    Not an exact equality, and the tolerance is not slop. `Money`
    quantizes every stored value to 2dp on write (db_types.py), while
    snapshot_service accumulates `investable_value` at full precision and
    rounds once when it writes the `total` row. So the sum of the rounded
    parts and the rounded sum can differ by up to half a cent per
    contributing row — on a real portfolio that is a couple of cents, and
    it is a property of the snapshot engine, not of this endpoint.
    Bounding it by the actual row count keeps the assertion tight enough
    to catch a genuine scope error (which would be off by whole holdings,
    not fractions of a cent) while not failing on arithmetic that is
    working as designed.
    """
    from app.models import DailySnapshot

    _setup_mixed_portfolio(client, auth_headers, db_session)

    body = client.get(
        "/api/allocation/breakdown",
        params={"dimension": dimension, "scope": scope},
        headers=auth_headers,
    ).json()
    total = sum(Decimal(b["value_eur"]) for b in body["buckets"])

    row_count = (
        db_session.query(DailySnapshot)
        .filter(DailySnapshot.scope_type.in_(["position", "cash_account", "loan"]))
        .count()
    )
    tolerance = Decimal("0.005") * row_count

    networth = client.get(
        "/api/timeseries/networth", params={"scope": scope}, headers=auth_headers
    ).json()
    assert Decimal(networth[-1]["value_eur"]) == pytest.approx(total, abs=tolerance)
    # The endpoint's own `total_eur` must match its buckets exactly, with
    # no tolerance — that one is pure addition inside a single response.
    assert Decimal(body["total_eur"]) == total


def test_scopes_nest_the_way_the_snapshot_engine_defines_them(
    client, auth_headers, db_session
):
    """investable ⊂ gross, and net is gross minus liabilities. Asserted
    through the endpoint so a future change to either definition has to
    break something visible."""
    _setup_mixed_portfolio(client, auth_headers, db_session)

    def total(scope):
        body = client.get(
            "/api/allocation/breakdown",
            params={"dimension": "asset_class", "scope": scope},
            headers=auth_headers,
        ).json()
        return Decimal(body["total_eur"])

    assert total("gross") >= total("investable")
    assert total("net") <= total("gross")


# --- the dimensions -------------------------------------------------------


def test_currency_dimension_reports_the_instruments_own_currency(
    client, auth_headers, db_session
):
    """A EUR-quoted fund holding dollar assets is beyond what this can
    see, but an explicitly USD-denominated instrument must not be
    reported as EUR just because its value is converted for display."""
    _setup_mixed_portfolio(client, auth_headers, db_session)

    body = client.get(
        "/api/allocation/breakdown",
        params={"dimension": "currency", "scope": "investable"},
        headers=auth_headers,
    ).json()
    keys = {b["key"] for b in body["buckets"]}
    assert "USD" in keys
    assert "EUR" in keys
    # 5 x 200 USD x 0.90 = 900.00 EUR
    usd = next(b for b in body["buckets"] if b["key"] == "USD")
    assert Decimal(usd["value_eur"]) == Decimal("900.00")


def test_liquidity_dimension_surfaces_unclassified_rather_than_guessing(
    client, auth_headers, db_session
):
    """`liquidity_tier` is nullable and, in practice, unset on most
    instruments. Bucketing those under a plausible tier would invent a
    domain rule and hide the fact that the field needs filling in; they
    get their own bucket instead."""
    _setup_mixed_portfolio(client, auth_headers, db_session)

    body = client.get(
        "/api/allocation/breakdown",
        params={"dimension": "liquidity", "scope": "investable"},
        headers=auth_headers,
    ).json()
    buckets = {b["key"]: Decimal(b["value_eur"]) for b in body["buckets"]}
    assert "T1" in buckets
    # Gold (no tier) and the cash account (no instrument at all) both land
    # in the unclassified bucket rather than being assumed into one.
    assert buckets[""] == Decimal("200.00") + Decimal("2000.00")


def test_account_dimension_names_accounts_not_ids(client, auth_headers, db_session):
    accounts, _ = _setup_mixed_portfolio(client, auth_headers, db_session)

    body = client.get(
        "/api/allocation/breakdown",
        params={"dimension": "account", "scope": "net"},
        headers=auth_headers,
    ).json()
    labels = {b["label"] for b in body["buckets"]}
    assert "Depot" in labels
    assert "Giro" in labels


def test_buckets_come_back_largest_first(client, auth_headers, db_session):
    _setup_mixed_portfolio(client, auth_headers, db_session)
    body = client.get(
        "/api/allocation/breakdown",
        params={"dimension": "asset_class", "scope": "investable"},
        headers=auth_headers,
    ).json()
    values = [Decimal(b["value_eur"]) for b in body["buckets"]]
    assert values == sorted(values, reverse=True)


def test_rejects_an_unknown_dimension(client, auth_headers, db_session):
    _setup_mixed_portfolio(client, auth_headers, db_session)
    resp = client.get(
        "/api/allocation/breakdown",
        params={"dimension": "sector", "scope": "investable"},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_dimension"


def test_rejects_an_unknown_scope(client, auth_headers, db_session):
    _setup_mixed_portfolio(client, auth_headers, db_session)
    resp = client.get(
        "/api/allocation/breakdown",
        params={"dimension": "currency", "scope": "everything"},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_scope"


def test_breakdown_on_an_empty_database_is_empty(client, auth_headers):
    body = client.get(
        "/api/allocation/breakdown",
        params={"dimension": "currency", "scope": "investable"},
        headers=auth_headers,
    ).json()
    assert body["buckets"] == []
    assert Decimal(body["total_eur"]) == 0


# --- concentration --------------------------------------------------------


def test_concentration_reports_the_three_specified_figures(
    client, auth_headers, db_session
):
    _setup_mixed_portfolio(client, auth_headers, db_session)

    body = client.get("/api/concentration", headers=auth_headers).json()
    for field in ("hhi", "effective_holdings", "top_n_share", "largest_share", "top_n"):
        assert field in body, field

    # Holdings are 1000 (EUR ETF), 900 (USD ETF) and 200 (gold) = 2100.
    assert body["largest_share"] == pytest.approx(1000 / 2100, abs=1e-6)
    assert body["top_n_share"] == pytest.approx(1.0, abs=1e-6)
    assert body["holdings_count"] == 3


def test_concentration_rows_agree_with_the_headline_figures(
    client, auth_headers, db_session
):
    """The rows are what makes the index checkable by eye, so the largest
    row's share must be exactly the reported largest_share."""
    _setup_mixed_portfolio(client, auth_headers, db_session)

    body = client.get("/api/concentration", headers=auth_headers).json()
    rows = body["holdings"]
    assert [r["share"] for r in rows] == sorted((r["share"] for r in rows), reverse=True)
    assert rows[0]["share"] == pytest.approx(body["largest_share"], abs=1e-9)
    assert sum(r["share"] for r in rows) == pytest.approx(1.0, abs=1e-6)


def test_concentration_hhi_matches_the_pure_function(client, auth_headers, db_session):
    from app.concentration_service import herfindahl_index

    _setup_mixed_portfolio(client, auth_headers, db_session)
    body = client.get("/api/concentration", headers=auth_headers).json()
    expected = herfindahl_index([Decimal(1000), Decimal(900), Decimal(200)])
    assert body["hhi"] == pytest.approx(expected, abs=1e-6)


def test_concentration_excludes_physical_assets(client, auth_headers, db_session):
    """A house would dominate every one of these figures and make "largest
    single weight" mean something entirely different from what spec 4.4
    asks for. Concentration is about the tradeable book."""
    _setup_mixed_portfolio(client, auth_headers, db_session)
    body = client.get("/api/concentration", headers=auth_headers).json()
    assert {r["name"] for r in body["holdings"]} == {"Euro ETF", "Dollar ETF", "Gold"}


def test_concentration_top_n_is_adjustable(client, auth_headers, db_session):
    _setup_mixed_portfolio(client, auth_headers, db_session)
    body = client.get(
        "/api/concentration", params={"top_n": 1}, headers=auth_headers
    ).json()
    assert body["top_n"] == 1
    assert body["top_n_share"] == pytest.approx(body["largest_share"], abs=1e-9)


def test_concentration_rejects_an_absurd_top_n(client, auth_headers, db_session):
    _setup_mixed_portfolio(client, auth_headers, db_session)
    resp = client.get(
        "/api/concentration", params={"top_n": 0}, headers=auth_headers
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_top_n"


def test_concentration_on_an_empty_database_is_null_not_zero(client, auth_headers):
    """Zero is the least-concentrated reading on the HHI scale, so an
    empty portfolio must not report it — that would render "nothing" as
    "perfectly diversified"."""
    body = client.get("/api/concentration", headers=auth_headers).json()
    assert body["hhi"] is None
    assert body["largest_share"] is None
    assert body["holdings"] == []
