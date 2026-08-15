# Cairn

Self-hosted net worth and portfolio tracker. Brokerage accounts, crypto,
precious metals, real estate and loans in one ledger — with an agent-friendly
API for booking data from statements and screenshots.

A cairn is a pile of stones on a mountain path: each passer-by adds one, and it
marks where you stand. Which is roughly how this thing gets its data.

## What it does

- **One ledger for everything** — two brokerage accounts (with overlapping
  holdings), crypto, physical gold and silver, a house, a mortgage, a car, cash
- **Derived, never entered** — holdings, cost basis and valuations all follow
  from transactions, so backfilling history months later just works
- **Honest about estimates** — the house tracks a price index, the car follows a
  depreciation model, and neither is ever rendered like a market price
- **Real return metrics** — TWR and IRR, plus an attribution waterfall that
  separates "I saved" from "the market moved"
- **Prices without API keys** — keyless public sources, cached locally
- **Offline-first PWA** — the Pi lives on the LAN; away from home the app shows
  the last known state with a visible timestamp
- **Bilingual** — German by default, English switchable, light/dark/system theme

## What it deliberately does not do

It holds no credentials and **moves no money**. No broker integration, no
banking connection, no payment capability. The worst case is disclosure, not
loss — and that is what makes the rest of the security model tractable.

## Status

Planning. The functional specification is written; the technical architecture is
being decided. See `docs/adr/`.

## Documentation

| Document | Contents |
|---|---|
| [`docs/spec.md`](docs/spec.md) | full specification — chapters 1–5, 7, 10–11 binding; 6, 8, 9 advisory |
| [`docs/agent-workflows.md`](docs/agent-workflows.md) | worked import scenarios |
| [`AGENTS.md`](AGENTS.md) | conventions and hard rules for coding agents |
| [`docs/adr/`](docs/adr/) | architecture decisions, with reasoning |

## Licence

Private project. No licence granted.
