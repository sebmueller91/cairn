"""Bug 1: FastAPI's default RequestValidationError shape is a *list* of
error dicts (`{"detail": [{"type": ..., "loc": ..., "msg": ...}]}`), but
frontend/src/lib/api.ts reads `body.detail.code` — every validation error
in the app used to collapse to the generic "generic" ApiError code with
nothing translatable. A German user typing "2000,50" into a Decimal query
param is the concrete case AGENTS.md/the bug report calls out.

Also covers the companion bug: an unhandled exception used to return a
plain-text "Internal Server Error" body (content-type: text/plain), which
`response.json()` in the SPA throws on.

Invented ISINs, quantities and amounts only, per AGENTS.md.
"""


def _assert_readable_error(response, status_code: int, code: str | None = None):
    assert response.status_code == status_code
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert isinstance(body["detail"], dict), (
        f"detail must be an object with a 'code' key, not FastAPI's raw list: {body['detail']!r}"
    )
    assert "code" in body["detail"]
    assert isinstance(body["detail"]["params"], dict)
    if code is not None:
        assert body["detail"]["code"] == code
    return body["detail"]


# --- The concrete German-locale case named in the bug report ---


def test_tax_allowance_german_decimal_comma_is_a_readable_error(client, auth_headers):
    # "2000,50" is exactly what a German user types into a Decimal field —
    # FastAPI/pydantic reject it (Decimal parsing wants "2000.50"), and
    # that rejection must itself be translatable, not a raw pydantic dump.
    resp = client.get("/api/tax", params={"allowance": "2000,50"}, headers=auth_headers)
    detail = _assert_readable_error(resp, 422, code="invalid_decimal")
    assert detail["params"]["field"] == "allowance"
    assert detail["params"]["location"] == "query"


def test_tax_year_non_integer_is_a_readable_error(client, auth_headers):
    resp = client.get("/api/tax", params={"year": "abc"}, headers=auth_headers)
    detail = _assert_readable_error(resp, 422, code="invalid_integer")
    assert detail["params"]["field"] == "year"


def test_timeseries_from_invalid_date_is_a_readable_error(client, auth_headers):
    resp = client.get(
        "/api/timeseries/networth", params={"from": "notadate"}, headers=auth_headers
    )
    detail = _assert_readable_error(resp, 422, code="invalid_date")
    assert detail["params"]["field"] == "from"


def test_transactions_limit_non_integer_is_a_readable_error(client, auth_headers):
    resp = client.get("/api/transactions", params={"limit": "abc"}, headers=auth_headers)
    detail = _assert_readable_error(resp, 422, code="invalid_integer")
    assert detail["params"]["field"] == "limit"


def test_milestones_assumed_return_non_decimal_is_a_readable_error(client, auth_headers):
    resp = client.get("/api/milestones", params={"assumed_return": "abc"}, headers=auth_headers)
    detail = _assert_readable_error(resp, 422, code="invalid_decimal")
    assert detail["params"]["field"] == "assumed_return"


def test_house_index_missing_required_field_is_a_readable_error(client, auth_headers):
    resp = client.post(
        "/api/house-index",
        json={"date": "2024-01-01", "index_value": "123.4"},
        headers=auth_headers,
    )
    detail = _assert_readable_error(resp, 422, code="missing_param")
    assert detail["params"]["field"] == "series"
    assert detail["params"]["location"] == "body"


def test_valuations_missing_required_field_is_a_readable_error(client, auth_headers):
    resp = client.post(
        "/api/valuations",
        json={"date": "2024-01-01", "value_eur": "100000"},
        headers=auth_headers,
    )
    detail = _assert_readable_error(resp, 422, code="missing_param")
    assert detail["params"]["field"] == "instrument_id"


def test_post_body_error_is_a_readable_error_not_a_list(client, auth_headers):
    # Any POST body validation failure, not just query params — instruments
    # is one of the routers this pass owns, so it doubles as a fixed bug
    # rather than only exercising other agents' code.
    resp = client.post(
        "/api/instruments",
        json={"asset_class": "EQUITY", "valuation_mode": "MARKET", "currency": "EUR"},
        headers=auth_headers,
    )
    detail = _assert_readable_error(resp, 422, code="missing_param")
    assert detail["params"]["field"] == "name"


def test_multiple_validation_errors_still_yield_one_readable_code(client, auth_headers):
    resp = client.get(
        "/api/tax", params={"year": "abc", "allowance": "2000,50"}, headers=auth_headers
    )
    detail = _assert_readable_error(resp, 422)
    assert detail["params"]["error_count"] == 2


# --- The other half of bug 1: unhandled exceptions must not leak plain text ---


def test_unhandled_exception_returns_json_not_plain_text(monkeypatch):
    # Starlette's ServerErrorMiddleware sends our handler's response to the
    # client and *then* re-raises the original exception regardless (so a
    # real ASGI server can still log it) — the default `client` fixture's
    # TestClient surfaces that re-raise as a test failure, which is the
    # right default for catching real bugs but wrong for this test, which
    # is specifically checking the response a real client receives.
    # raise_server_exceptions=False matches what a deployed client sees.
    from starlette.testclient import TestClient

    from app.main import app
    from app.routers import health as health_module

    def _boom(db, key):
        raise RuntimeError("simulated failure for test_error_contract, not a real crash")

    monkeypatch.setattr(health_module.kv_store, "get", _boom)

    client = TestClient(app, base_url="https://testserver", raise_server_exceptions=False)
    resp = client.get("/api/health")
    assert resp.status_code == 500
    assert resp.headers["content-type"].startswith("application/json")
    # response.json() must not raise — this is exactly what broke the SPA
    # before: a text/plain body that .json() throws on.
    body = resp.json()
    assert body["detail"]["code"] == "internal_error"
    assert isinstance(body["detail"]["params"], dict)
    # The exception message/traceback must never reach the client.
    assert "RuntimeError" not in resp.text
    assert "simulated failure" not in resp.text
