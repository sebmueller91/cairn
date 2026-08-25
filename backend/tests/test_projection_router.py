"""The projection endpoint (spec 4.6, forward): assembles the real
snapshot value and the trailing savings rate into the projection maths
unit-tested in test_projection_service.py.

What is checked here is mostly the honesty of the response rather than
the arithmetic — that the assumptions come back with the numbers, that a
derived savings rate is distinguishable from one the caller supplied, and
that nonsense parameters are refused instead of silently producing a
confident-looking curve.

Invented ISINs and quantities only, per AGENTS.md.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest


def _setup_portfolio(client, auth_headers, db_session):
    """A holding bought a year ago, plus a cash account, so both the
    snapshot total and the trailing savings rate are non-zero."""
    from app.models import PricePoint

    account = client.post(
        "/api/accounts",
        json={"name": "Depot", "type": "BROKERAGE", "currency": "EUR"},
        headers=auth_headers,
    ).json()["id"]
    instrument = client.post(
        "/api/instruments",
        json={
            "name": "Projektions ETF", "isin": "XX0000000950",
            "asset_class": "EQUITY", "valuation_mode": "MARKET", "currency": "EUR",
        },
        headers=auth_headers,
    ).json()["id"]

    bought = date.today() - timedelta(days=400)
    for d, close in [(bought, "100.00"), (date.today(), "120.00")]:
        db_session.add(
            PricePoint(
                instrument_id=instrument, date=d, close=Decimal(close),
                currency="EUR", provider="test", quality="ok",
            )
        )
    db_session.commit()

    # A purchase every 60 days for the last year, so the trailing
    # twelve-month savings rate has something real to average.
    for n in range(6):
        d = date.today() - timedelta(days=330 - n * 60)
        client.post(
            "/api/transactions",
            json={
                "external_id": f"proj-buy-{n}", "date": d.isoformat(), "type": "BUY",
                "account_id": account, "instrument_id": instrument,
                "quantity": "5", "price": "100.00", "currency": "EUR",
            },
            headers=auth_headers,
        )
    client.post("/api/admin/rebuild-snapshots", headers=auth_headers)
    return account, instrument


def test_projects_one_point_per_month_over_the_horizon(client, auth_headers, db_session):
    _setup_portfolio(client, auth_headers, db_session)

    resp = client.get("/api/projection", params={"years": 5}, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["points"]) == 60
    dates = [p["date"] for p in body["points"]]
    assert dates == sorted(dates)
    assert len(set(dates)) == len(dates)


def test_the_cone_widens_and_never_crosses(client, auth_headers, db_session):
    """low <= mid <= high at every point, by construction. A crossing
    would mean the pessimistic case had somehow beaten the optimistic
    one, which can only be an arithmetic or ordering bug."""
    _setup_portfolio(client, auth_headers, db_session)

    body = client.get(
        "/api/projection",
        params={"years": 10, "annual_return_pct": "5", "return_spread_pp": "2"},
        headers=auth_headers,
    ).json()

    assert body["return_low_pct"] == "3"
    assert body["return_high_pct"] == "7"
    for p in body["points"]:
        assert Decimal(p["low_eur"]) <= Decimal(p["mid_eur"]) <= Decimal(p["high_eur"])

    # And it genuinely widens — a cone that stays a line says nothing
    # about uncertainty.
    first, last = body["points"][0], body["points"][-1]
    assert (Decimal(last["high_eur"]) - Decimal(last["low_eur"])) > (
        Decimal(first["high_eur"]) - Decimal(first["low_eur"])
    )


def test_zero_spread_collapses_the_cone_to_a_line(client, auth_headers, db_session):
    _setup_portfolio(client, auth_headers, db_session)

    body = client.get(
        "/api/projection",
        params={"years": 3, "return_spread_pp": "0"},
        headers=auth_headers,
    ).json()
    for p in body["points"]:
        assert p["low_eur"] == p["mid_eur"] == p["high_eur"]


def test_the_response_carries_every_assumption_it_used(client, auth_headers, db_session):
    """A projection without its assumptions attached is unreadable — the
    same curve means completely different things at 3% and at 8%. The UI
    must never have to guess, or worse, restate a default it thinks the
    server used."""
    _setup_portfolio(client, auth_headers, db_session)

    body = client.get("/api/projection", headers=auth_headers).json()
    for field in (
        "scope", "start_date", "start_value_eur", "monthly_savings_eur",
        "monthly_savings_source", "annual_return_pct", "return_low_pct",
        "return_high_pct", "annual_inflation_pct", "real",
    ):
        assert field in body, field


def test_savings_rate_is_derived_by_default_and_says_so(client, auth_headers, db_session):
    _setup_portfolio(client, auth_headers, db_session)

    body = client.get("/api/projection", headers=auth_headers).json()
    assert body["monthly_savings_source"] == "derived"
    # The trailing twelve months held six purchases of 500 each.
    assert Decimal(body["monthly_savings_eur"]) > 0


def test_an_overridden_savings_rate_is_used_and_flagged(client, auth_headers, db_session):
    """"What if I saved 1000 a month" is the question this view exists to
    answer. An override that came back indistinguishable from a measured
    figure would be the worst of both."""
    _setup_portfolio(client, auth_headers, db_session)

    body = client.get(
        "/api/projection",
        params={"monthly_savings_eur": "1000", "years": 1, "annual_return_pct": "0",
                "return_spread_pp": "0"},
        headers=auth_headers,
    ).json()
    assert body["monthly_savings_source"] == "override"
    assert Decimal(body["monthly_savings_eur"]) == Decimal("1000")
    # No growth assumed, so twelve months adds exactly twelve thousand.
    grown = Decimal(body["points"][-1]["mid_eur"]) - Decimal(body["start_value_eur"])
    assert grown == pytest.approx(Decimal(12000), abs=Decimal("0.01"))


def test_a_zero_override_is_honoured_not_treated_as_absent(client, auth_headers, db_session):
    """"What if I stopped contributing" is a real question, and 0 is a
    falsy value — the classic way an override gets silently dropped."""
    _setup_portfolio(client, auth_headers, db_session)

    body = client.get(
        "/api/projection",
        params={"monthly_savings_eur": "0", "years": 1, "annual_return_pct": "0",
                "return_spread_pp": "0"},
        headers=auth_headers,
    ).json()
    assert body["monthly_savings_source"] == "override"
    assert Decimal(body["monthly_savings_eur"]) == 0
    assert Decimal(body["points"][-1]["mid_eur"]) == Decimal(body["start_value_eur"])


def test_real_terms_sit_below_nominal_under_positive_inflation(client, auth_headers, db_session):
    _setup_portfolio(client, auth_headers, db_session)

    params = {"years": 10, "annual_inflation_pct": "2"}
    nominal = client.get("/api/projection", params=params, headers=auth_headers).json()
    real = client.get(
        "/api/projection", params={**params, "real": "true"}, headers=auth_headers
    ).json()

    assert real["real"] is True
    assert nominal["real"] is False
    assert Decimal(real["points"][-1]["mid_eur"]) < Decimal(
        nominal["points"][-1]["mid_eur"]
    )


def test_real_equals_nominal_at_zero_inflation(client, auth_headers, db_session):
    _setup_portfolio(client, auth_headers, db_session)

    params = {"years": 5, "annual_inflation_pct": "0"}
    nominal = client.get("/api/projection", params=params, headers=auth_headers).json()
    real = client.get(
        "/api/projection", params={**params, "real": "true"}, headers=auth_headers
    ).json()
    assert [p["mid_eur"] for p in real["points"]] == [
        p["mid_eur"] for p in nominal["points"]
    ]


def test_real_terms_never_consult_the_cpi_series(client, auth_headers, db_session):
    """The trap this feature is most likely to fall into. Deflating a
    *future* date against the CPI table carries the last known index
    forward, giving a factor of exactly 1.0 — the projection would come
    back unchanged and be labelled "in today's money". Loading a CPI
    series must therefore change nothing here.
    """
    from app.models import CpiIndexPoint

    _setup_portfolio(client, auth_headers, db_session)
    params = {"years": 5, "annual_inflation_pct": "3", "real": "true"}
    before = client.get("/api/projection", params=params, headers=auth_headers).json()

    for year, value in [(2020, "100.0"), (2024, "118.5")]:
        db_session.add(
            CpiIndexPoint(date=date(year, 1, 1), index_value=Decimal(value))
        )
    db_session.commit()

    after = client.get("/api/projection", params=params, headers=auth_headers).json()
    assert [p["mid_eur"] for p in after["points"]] == [
        p["mid_eur"] for p in before["points"]
    ]


def test_starts_from_the_latest_snapshot_value(client, auth_headers, db_session):
    _setup_portfolio(client, auth_headers, db_session)

    body = client.get("/api/projection", headers=auth_headers).json()
    networth = client.get(
        "/api/timeseries/networth", params={"scope": "net"}, headers=auth_headers
    ).json()
    assert Decimal(body["start_value_eur"]) == Decimal(networth[-1]["value_eur"])
    assert body["start_date"] == networth[-1]["date"]


def test_scope_selects_which_notion_of_wealth_is_projected(client, auth_headers, db_session):
    _setup_portfolio(client, auth_headers, db_session)

    for scope in ("net", "gross", "investable"):
        resp = client.get(
            "/api/projection", params={"scope": scope}, headers=auth_headers
        )
        assert resp.status_code == 200
        assert resp.json()["scope"] == scope


# --- refusals -------------------------------------------------------------


def test_rejects_an_unknown_scope(client, auth_headers, db_session):
    _setup_portfolio(client, auth_headers, db_session)
    resp = client.get(
        "/api/projection", params={"scope": "portfolio"}, headers=auth_headers
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_scope"


@pytest.mark.parametrize("years", [0, -1, 200])
def test_rejects_an_implausible_horizon(client, auth_headers, db_session, years):
    _setup_portfolio(client, auth_headers, db_session)
    resp = client.get(
        "/api/projection", params={"years": years}, headers=auth_headers
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_horizon"


def test_rejects_a_negative_spread(client, auth_headers, db_session):
    """A negative spread would put `low` above `high` and invert the cone
    everywhere downstream."""
    _setup_portfolio(client, auth_headers, db_session)
    resp = client.get(
        "/api/projection", params={"return_spread_pp": "-1"}, headers=auth_headers
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_spread"


@pytest.mark.parametrize(
    "param,value",
    [
        ("annual_return_pct", "nan"),
        ("annual_return_pct", "Infinity"),
        ("annual_inflation_pct", "nan"),
        ("return_spread_pp", "Infinity"),
        ("monthly_savings_eur", "nan"),
    ],
)
def test_rejects_non_finite_assumptions(client, auth_headers, db_session, param, value):
    """Decimal("nan") and Decimal("Infinity") parse without raising, and
    unchecked they would propagate into the compounding loop and come
    back as a curve of NaNs behind a 200 (the trap routers/allocation.py
    documents).

    Here they are caught one layer earlier, by pydantic at the query
    boundary, and main.py's RequestValidationError handler turns that
    into the app's readable {code, params} contract rather than a raw
    pydantic dump. Asserted at that layer because that is where it
    actually happens — the service-level guard behind it is unreachable
    over HTTP and is kept only for direct callers."""
    _setup_portfolio(client, auth_headers, db_session)
    resp = client.get("/api/projection", params={param: value}, headers=auth_headers)
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["code"] == "invalid_value"
    assert detail["params"]["field"] == param


@pytest.mark.parametrize(
    "param,value",
    [("annual_return_pct", "5000"), ("annual_inflation_pct", "-500")],
)
def test_rejects_absurd_rates(client, auth_headers, db_session, param, value):
    _setup_portfolio(client, auth_headers, db_session)
    resp = client.get("/api/projection", params={param: value}, headers=auth_headers)
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "invalid_assumption"


def test_empty_database_projects_nothing_rather_than_a_zero_line(client, auth_headers):
    """With no snapshot there is no starting value. A flat line at zero
    would look like a real answer ("you will have nothing"); an empty
    series lets the UI say it has nothing to project from."""
    resp = client.get("/api/projection", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["points"] == []
