# Cairn MCP server

A thin translation layer between MCP and Cairn's REST API (spec 7.5's
"optional extension": *"a small MCP server in front of the API. Bookings
then become native tool calls with schema validation at the tool
level."*). Every tool here calls the same endpoints
[`docs/agent-workflows.md`](../docs/agent-workflows.md) documents for raw
curl — no business logic is duplicated, the API stays the one source of
truth.

Runs over stdio, launched locally by an MCP client (Claude Code, Claude
Desktop) on your own machine — it is not deployed to the Pi. It reaches
Cairn over the LAN exactly like an agent using curl would: HTTPS, bearer
token.

## Setup

```bash
cd mcp_server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuring Claude Code

```bash
claude mcp add cairn \
  --env CAIRN_API_URL=https://raspberrypi5 \
  --env CAIRN_API_TOKEN=<your token, from the password manager> \
  -- /absolute/path/to/mcp_server/.venv/bin/python /absolute/path/to/mcp_server/server.py
```

Or add directly to `.mcp.json`:

```json
{
  "mcpServers": {
    "cairn": {
      "command": "/absolute/path/to/mcp_server/.venv/bin/python",
      "args": ["/absolute/path/to/mcp_server/server.py"],
      "env": {
        "CAIRN_API_URL": "https://raspberrypi5",
        "CAIRN_API_TOKEN": "<your token>"
      }
    }
  }
}
```

Only reachable while both your machine and the Pi are on the LAN — same
reach as everything else in this project (spec 6.3: no remote access).

## Tools

Reads: `get_health`, `list_accounts`, `list_instruments`,
`get_positions`, `list_transactions`, `get_networth`, `get_data_quality`.

Writes: `create_account`, `create_instrument`, `book_transaction`,
`reconcile_holdings`. `book_transaction` supports `dry_run=true` per
spec 7's agent design — validate before writing.

TLS verification is disabled for the mkcert leaf cert (ADR 0014), same
as `scripts/backup.sh` — this process's trust store never has the mkcert
CA installed, and it's talking to your own LAN, not the internet.
