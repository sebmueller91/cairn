"""MCP server fronting Cairn's REST API (spec 7.5's "optional extension":
"a small MCP server in front of the API. Bookings then become native tool
calls with schema validation at the tool level.") — a thin translation
layer, not a second implementation of any business logic. Every tool here
just calls the same endpoints docs/agent-workflows.md already documents
for raw curl, so validation, idempotency, and error codes all come from
the one real source of truth (the API itself), not a duplicate copy of
its rules.

Runs over stdio, meant to be launched locally by an MCP client (Claude
Code, Claude Desktop) — see README.md for configuration. Talks to the
Cairn API over HTTPS using the same bearer token an agent would use with
curl, read from CAIRN_API_TOKEN.
"""

import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

API_URL = os.environ.get("CAIRN_API_URL", "https://raspberrypi5")
API_TOKEN = os.environ.get("CAIRN_API_TOKEN")

mcp = FastMCP("cairn")


def _client() -> httpx.AsyncClient:
    if not API_TOKEN:
        raise RuntimeError("CAIRN_API_TOKEN is not set")
    return httpx.AsyncClient(
        base_url=API_URL,
        headers={"Authorization": f"Bearer {API_TOKEN}"},
        # The mkcert leaf cert (ADR 0014) isn't in this process's trust
        # store — same LAN-only trust boundary as scripts/backup.sh.
        verify=False,
        timeout=30.0,
    )


async def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    async with _client() as client:
        resp = await client.get(path, params={k: v for k, v in (params or {}).items() if v is not None})
        resp.raise_for_status()
        return resp.json()


async def _post(
    path: str, body: dict[str, Any], params: dict[str, Any] | None = None
) -> Any:
    async with _client() as client:
        resp = await client.post(
            path,
            json={k: v for k, v in body.items() if v is not None},
            params={k: v for k, v in (params or {}).items() if v is not None},
        )
        if not resp.is_success:
            raise RuntimeError(f"{resp.status_code}: {resp.text}")
        return resp.json()


# --- Reads ---


@mcp.tool()
async def get_health() -> dict:
    """Cairn's health status: database reachability, last price fetch,
    last snapshot rebuild, last successful backup."""
    return await _get("/api/health")


@mcp.tool()
async def list_accounts() -> list[dict]:
    """All accounts (brokerage, crypto wallet, cash, real estate, vehicle, loan)."""
    return await _get("/api/accounts")


@mcp.tool()
async def list_instruments(search: str | None = None) -> list[dict]:
    """All instruments (ETFs, stocks, crypto, house, car, ...), optionally
    filtered by a name/ISIN/ticker search string."""
    return await _get("/api/instruments", {"search": search})


@mcp.tool()
async def get_positions(
    account_id: int | None = None, group_by: str = "instrument"
) -> list[dict]:
    """Current holdings with quantity, cost basis, and current value.
    group_by is 'instrument' or 'account'."""
    return await _get("/api/positions", {"account_id": account_id, "group_by": group_by})


@mcp.tool()
async def list_transactions(
    account_id: int | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Booked transactions, most recent first. Dates are YYYY-MM-DD."""
    # Param names here must match the router's query params exactly
    # (spec 7.1: GET /api/transactions?from=&to=) — FastAPI silently drops
    # unknown query params rather than erroring, so a mismatch here doesn't
    # fail loudly, it just makes date filtering a silent no-op.
    return await _get(
        "/api/transactions",
        {"account_id": account_id, "from": from_date, "to": to_date, "limit": limit},
    )


@mcp.tool()
async def get_networth(
    from_date: str | None = None,
    to_date: str | None = None,
    granularity: str = "day",
    scope: str = "investable",
) -> list[dict]:
    """Net worth time series. scope is 'investable', 'gross', or 'net'
    (spec 4.1's three wealth perspectives)."""
    return await _get(
        "/api/timeseries/networth",
        {"from": from_date, "to": to_date, "granularity": granularity, "scope": scope},
    )


@mcp.tool()
async def get_data_quality() -> dict:
    """Stale/missing prices, stale valuations, positions with no cost
    basis, and backup staleness — data quality issues that should be
    fixed before trusting a number."""
    return await _get("/api/data-quality")


# --- Writes ---


@mcp.tool()
async def create_account(
    name: str,
    type: str,
    currency: str = "EUR",
    institution: str | None = None,
) -> dict:
    """Create an account. type is one of BROKERAGE, CRYPTO_WALLET,
    PHYSICAL_STORAGE, REAL_ESTATE, VEHICLE, LOAN, CASH."""
    return await _post(
        "/api/accounts",
        {"name": name, "type": type, "currency": currency, "institution": institution},
    )


@mcp.tool()
async def create_instrument(
    name: str,
    asset_class: str,
    valuation_mode: str,
    currency: str = "EUR",
    isin: str | None = None,
    ticker: str | None = None,
) -> dict:
    """Create an instrument. asset_class: EQUITY, BOND, COMMODITY, CRYPTO,
    REAL_ESTATE, VEHICLE, CASH, LIABILITY. valuation_mode: MARKET (priced
    instrument), ANCHORED (house), MODELED (car), NOMINAL (cash)."""
    return await _post(
        "/api/instruments",
        {
            "name": name,
            "asset_class": asset_class,
            "valuation_mode": valuation_mode,
            "currency": currency,
            "isin": isin,
            "ticker": ticker,
        },
    )


@mcp.tool()
async def book_transaction(
    external_id: str,
    date: str,
    type: str,
    account_id: int,
    instrument_id: int | None = None,
    quantity: str | None = None,
    price: str | None = None,
    amount: str | None = None,
    currency: str = "EUR",
    fees: str | None = None,
    tax: str | None = None,
    counter_account_id: int | None = None,
    note: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Book one transaction. external_id must be unique and stable —
    resending the same external_id with identical fields is a no-op,
    with different fields is a 409 conflict (never a silent overwrite).
    type is one of BUY, SELL, DIVIDEND, INTEREST, FEE, TAX, DEPOSIT,
    WITHDRAWAL, TRANSFER, SPLIT, OPENING_BALANCE, BALANCE_STATEMENT,
    LOAN_PAYMENT, EXTRA_REPAYMENT. Quantities/prices/amounts are decimal
    strings, never floats. Set dry_run=true to run the full validation
    pipeline without writing anything — the endpoint runs the same checks
    (references, FX, price, holdings, external_id conflict) and rolls
    back instead of committing; the response is {"dry_run": true,
    "outcome": "would_create", "transaction": {...}}, never the plain
    booked record a real write returns, so it can't be mistaken for one."""
    return await _post(
        "/api/transactions",
        {
            "external_id": external_id,
            "date": date,
            "type": type,
            "account_id": account_id,
            "instrument_id": instrument_id,
            "quantity": quantity,
            "price": price,
            "amount": amount,
            "currency": currency,
            "fees": fees,
            "tax": tax,
            "counter_account_id": counter_account_id,
            "note": note,
        },
        params={"dry_run": dry_run},
    )


@mcp.tool()
async def reconcile_holdings(account: str, as_of: str, holdings: list[dict]) -> dict:
    """Compare a broker statement's holdings against the ledger's computed
    positions for one account. holdings is a list of {"isin": str,
    "quantity": str} — this never writes anything, it only reports
    differences for a human/agent to act on."""
    return await _post(
        "/api/reconcile", {"account": account, "as_of": as_of, "holdings": holdings}
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
