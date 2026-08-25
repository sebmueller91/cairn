# Cairn — net worth & portfolio cockpit

**Purpose of this document:** the functional and technical specification — the
authority on *what* is built and *why*, not every line of code. It began as the
brief handed to a coding agent and is now maintained alongside the
implementation: where the two disagree, that is a bug in one of them.

**Status:** implemented · single user · self-hosted · base currency EUR · UI German/English
**Chapters 1–5, 7, 10–11 are binding; 6, 8, 9 are advisory.**
**Repository:** `cairn` · **package:** `cairn` · **hostname on the LAN:** `<your-pi-hostname>`

---

## 1. Goal and scope

### Goal
A self-hosted web application that brings **total net worth** — liquid
investments, physical assets, liabilities — into one place and answers two
questions excellently:

1. **How has my net worth developed over time?** (time series, return,
   contributions vs. market movement)
2. **What is it made of right now?** (allocation, concentration risk, currency
   and liquidity structure)

### Non-goals
- No broker integration, no automated portfolio scraping, no order routing
- No tax filing, no binding tax calculations (informational metrics only)
- No multi-user capability, no tenancy
- No real-time tick streaming — end-of-day prices plus an optional intraday
  refresh are sufficient

### Guiding principles
| Principle | What it means in practice |
|---|---|
| **Ledger-first** | Transactions are the truth, not balances. Holdings and values are always *derived*. Every number is traceable and retroactively correctable. |
| **Agent-friendly** | Every write operation is available over REST: idempotent, validating, with legible errors. The UI is just a second front end onto the same API. |
| **Honest imprecision** | Illiquid assets (house, car) are estimates. They are labelled as such, with valuation source and age. An estimate is never rendered like a market price. |
| **Offline-capable** | The Pi lives on the home network only. The app must remain fully readable away from home using the last known state. |

---

## 2. Domain model

The model is deliberately generic: adding a new asset (a savings account, a
stake in something, a second car) must **never require a schema change**.

### 2.1 Core concepts

```
Account (brokerage, wallet, vault, property, vehicle, loan, cash)
  └── Position (Account × Instrument)
        └── Transaction (BUY, SELL, DIVIDEND, FEE, ...)

Instrument (ETF, share, crypto, precious metal, physical asset, liability)
  └── PriceSource (how is it valued?)
        └── PricePoint (time series)
```

**Account** = an organisational container with its own custodian.
Types: `BROKERAGE` (portfolio A, portfolio B), `CRYPTO_WALLET`,
`PHYSICAL_STORAGE` (vault or safe deposit box for gold and silver),
`REAL_ESTATE`, `VEHICLE`, `LOAN`, `CASH`.

**Instrument** = the thing being valued. An instrument exists **once** and may
sit in several accounts — which is how the portfolio overlap resolves cleanly:

> The MSCI World sits in portfolio A **and** portfolio B. There is *one*
> instrument `IE00B4L5Y983` with *one* price series and *two* positions. The
> overview can group by instrument (aggregated: "I hold 412 units") or by
> account (separately). Cost basis is tracked **per position**, because it is
> account-specific, and weighted together for the instrument view.

**Position** = the holding of one instrument in one account. Never written
directly; always materialised from transactions.

**Transaction** = the only write primitive (see 2.3).

### 2.2 Asset classes and valuation modes

Every instrument has exactly one **valuation mode**. This is the central abstraction:

| Mode | Meaning | Used for |
|---|---|---|
| `MARKET` | value = quantity × market price (fetched externally) | ETFs, shares, BTC, gold/silver (spot × fine weight) |
| `ANCHORED` | value = curve interpolated through manually set **valuation anchors** | house |
| `MODELED` | value = deterministic formula over time | car (depreciation) |
| `AMORTIZING_LIABILITY` | value = negative outstanding balance from the amortisation schedule | mortgage |
| `NOMINAL` | value = nominal amount | current/savings account |

Additional classification axes per instrument, all optional, all used for analysis:
`asset_class` (EQUITY, BOND, COMMODITY, CRYPTO, REAL_ESTATE, VEHICLE, CASH,
LIABILITY) · `region` · `sector` · `currency` · `liquidity_tier`
(T0 immediate / T1 days / T2 months / T3 illiquid) · `risk_bucket` · `tags[]`

### 2.3 Transaction types

| Type | Effect | Required fields |
|---|---|---|
| `BUY` | quantity +, cost basis + | quantity, price, fees, currency |
| `SELL` | quantity −, realised P/L | quantity, price, fees |
| `DIVIDEND` | income, no quantity effect | amount, tax_withheld |
| `INTEREST` | interest (account or loan) | amount |
| `FEE` | cost (custody fee, vault storage) | amount |
| `TAX` | tax withheld | amount |
| `DEPOSIT` / `WITHDRAWAL` | external capital flow — **critical for TWR/IRR** | amount |
| `TRANSFER` | in-kind transfer between accounts, cost basis follows | from_account, to_account, quantity |
| `SPLIT` | factor applied to quantity and historical cost basis | ratio |
| `VALUATION` | sets a valuation anchor (optional, e.g. an appraisal) | value, source, confidence |
| `OPENING_BALANCE` | provisional starting holding at a cut-off date, replaceable later | quantity, value, provisional |
| `BALANCE_STATEMENT` | observed account balance on a date (cash) | balance |
| `LOAN_PAYMENT` | instalment → interest and principal split | amount, interest_part, principal_part |
| `EXTRA_REPAYMENT` | overpayment | amount |

Every transaction carries: `date`, `account_id`, `instrument_id?`, `amount_eur`
(converted, with the FX rate stored alongside), `note`, `source`
(`manual` / `agent` / `import`), `external_id`, `import_batch_id`, `created_at`.

### 2.4 Why a ledger rather than a list of balances

The extra effort pays for itself three times over:

- **Retroactive correction:** a mis-booked purchase from 2023 gets corrected and
  every metric and the entire history recomputes, with no data mess.
- **Real return metrics:** TWR and IRR strictly require the capital flows.
  Without a ledger you cannot separate performance from contributions — and that
  separation is the single most interesting number in the whole system.
- **Agent suitability:** an agent reading a statement naturally produces a list
  of transactions. The model accepts exactly that.

### 2.5 Data maturity — incremental refinement, including retroactively

Core requirement: material arrives over months, covering periods far in the past.
The app must always show an **honest picture** and must **never double-count**
when history is filled in behind existing entries.

**Four mechanisms:**

**1. Provisional opening balances.** You start with `OPENING_BALANCE` entries at
a cut-off date ("portfolio A held 412 units of X on 2024-01-01, cost basis
38,000"). They are flagged `provisional = true` and belong to an import batch.

**2. Supersede on backfill.** When the agent later imports real transactions from
*before* the cut-off, the app detects the overlap and offers
`POST /api/import-batches/{id}/supersede`:
- the holding at the cut-off is recomputed from the new history
- compared against the provisional opening balance → delta report
- on a match (tolerance configurable): the opening balance is voided and the real
  history takes over
- on a mismatch: a smaller residual `OPENING_BALANCE` remains, clearly flagged
  as unexplained

You can therefore backfill as often as you like without ever duplicating a holding.

**3. Precision levels per transaction.** Two extra fields:
- `date_precision`: `day | month | quarter | year` — sometimes all you know is
  "somewhere in spring 2019"
- `price_mode`: `exact | auto` — with `auto`, the app takes the price from its
  own price history at the (possibly fuzzy) date. Since Stooq provides full
  histories, this is not a crutch; for savings plans it is often more accurate
  than transcribed figures.

A purchase with an unknown price is therefore still bookable — and becomes exact
once you supply the document.

**4. `verified_from` per account.** The date from which the ledger is considered
complete. Consequences for presentation:
- the net worth curve before that date is drawn **dashed**, with a tooltip note
- **TWR and IRR are computed only from `verified_from` onwards.** A return over a
  period with estimated starting balances is a fabricated number; it is withheld
  rather than dressed up.
- a completeness panel: *"Portfolio A: complete since 03/2021 · Portfolio B:
  since 01/2024 · BTC: since inception"*

Because all metrics derive from the ledger and snapshots are only a cache, a
rebuild after each backfill is enough — the whole history recomputes and gets
more precise on its own.

---

## 3. Valuation logic in detail

### 3.1 Securities and crypto
Value = `quantity × price(instrument currency) × FX(→EUR)`. Prices **and** FX
rates are both stored as time series so historical valuations stay reproducible.
No back-computing with today's FX rate.

### 3.2 Precious metals
The instrument is a *physical unit*, not a spot price:
```
value_eur = fine_weight_grams × spot_eur_per_gram
```
Fine weight comes from `quantity` (pieces) × `fine_weight_g` per piece
(e.g. 31.1035 g for one troy ounce). Optional per position: `premium_pct`, the
premium over spot, which matters for coins. The purchase price is booked as cost
basis anyway, so the premium paid at purchase is visible either way.

### 3.3 Car — depreciation model
Fully automatic, no manual upkeep. One-off parameters at creation: purchase
price, purchase date, first registration, mileage at purchase, estimated annual
mileage. After that the model runs on its own.

**Model** (exponential with an immediate drop and a residual floor):
```
residual(t) = max(
    floor_pct × list_price,
    list_price × (1 − initial_drop) × exp(−k × t_years) × (1 − km_penalty)
)
```
Suggested values for Germany: `initial_drop = 0.20` (registration loss),
`k = 0.13` (≈ 12 % p.a. thereafter), `floor_pct = 0.10`,
`km_penalty = max(0, (driven_km − 15000 × t) / 100000) × 0.08`.

For a **used purchase**, the starting value is the purchase price rather than the
list price, and the effective vehicle age is derived from the first registration —
otherwise the model double-counts the depreciation already suffered.

**No manual effort.** There is no free API for vehicle residual values, and
calibration is not worth it here: with the car at a few percent of net worth,
even a 25 % model error moves the total by well under one percent. The
`VALUATION` anchor stays in the model regardless — if a figure ever lands in
your lap (a trade-in offer, an insurance estimate), the agent can book it in ten
seconds and the curve snaps to it from then on.

Always displayed with a badge: *"model value, estimated"* — never rendered like
a market price.

### 3.4 House
The starting point is a single anchor: the **purchase price** at the purchase
date. Further anchors (an appraisal, a bank valuation on refinancing) are
possible but not required.

**Decided: automatic index tracking.**
```
house_value(t) = anchor_value × index(t) / index(anchor_date)
```
Index: the German federal house price index (Destatis GENESIS table 61262,
series for one- and two-family houses, broken down by district type — for a rural
Bavarian district the regional series fits better than the national average).
Fetched quarterly by a job, no manual intervention. The index is published with
roughly one quarter of lag; the last known value is carried forward.

**What you accept in exchange — deliberately:**
- The index describes a district type, not your house. Location, condition and
  fittings are missing. Realistic spread: ±10–15 %.
- The net worth curve moves on an **assumption**, not on real money. Therefore:
  - property value changes get their **own bar** in the attribution waterfall
    ("valuation adjustments"), never mixed in with market gains
  - the property value is shown as a **band** (point value ± uncertainty
    corridor), not as an exact figure
  - a global toggle **"property at acquisition cost"** — one click and the entire
    history recomputes conservatively with no appreciation at all. Both truths
    remain available at any time.
- If the index fetch fails, the last known value is held (flat as fallback),
  visible in the data quality panel.

**Purchase costs** (transfer tax, notary, agent) do **not** enter the cost basis.
They are booked as a `FEE` against the cash account on the purchase date: the
money really was spent, so net worth drops correctly at that moment, but the
property return is not saddled with a ~10 % starting loss.

Value-adding investments (a new heating system, a roof) are booked as capital
contributions to the property account — they raise the cost basis, not
automatically the value.

### 3.5 Mortgage
A full annuity loan rather than "outstanding balance, a number I update
occasionally":
```
balance(n) = K0 × (1+i)^n − A × ((1+i)^n − 1) / i
```
with `i` the monthly rate, `A` the monthly payment, plus overpayments as events.
Stored: principal, interest rate, end of the fixed-rate period, payment, schedule.

Metrics that fall out of this: **LTV** (balance / current house value),
amortisation progress, cumulative interest paid, projected balance at the end of
the fixed-rate period, a countdown to refinancing, and the interest portion as a
running cost in the cash flow view.

### 3.6 Cash and capital flows

**Cash is tracked by balance only.** The agent occasionally books a
`BALANCE_STATEMENT` from a screenshot: "current account on 2026-07-31: 4,180".
No individual entries, no categories, no household budgeting. Between two
statements the balance is interpolated.

**Transfers are not recorded.** No `TRANSFER` between current account and
brokerage, no detection heuristics. This works because the capital flows that
matter are precisely known elsewhere:

**Derived settlement account per portfolio.** Each brokerage account keeps an
internal cash balance that follows purely from the securities transactions:
- purchase → balance falls by consideration + fees
- sale, dividend → balance rises
- if the balance goes negative, the app books the shortfall automatically as an
  **external deposit** on that date
- if money is left over (a dividend funding the next purchase), **no** deposit
  is created

Portfolio inflows are therefore exact with no extra work: you book only
purchases and sales, and the capital flows fall out. **TWR and IRR per portfolio
are consequently mathematically correct** — for a portfolio, a deposit is always
external regardless of which account it came from.

**Cash bridge against double counting.** Between two balance statements, known
portfolio deposits are already explained. The interpolation subtracts them
explicitly and spreads only the *unexplained* remainder linearly. Otherwise
5,000 would briefly appear twice in net worth: once in the stale account
balance, once in the portfolio.

**Savings rate as a residual.** What enters total wealth from outside is not
booked but computed:
```
external inflow (period) = Δ net worth
                          − market result − income + costs
                          − valuation adjustments (house/car)
```
This is the honest variant: no invented precision, and the resolution is
automatically as coarse as your balance statements. The display says so —
*"savings rate Q3: approx. 4,200 · derived from 2 balance statements"*. Book a
screenshot more often and the curve gets finer; skip it and you lose only this
one metric, not portfolio returns.

### 3.7 Snapshot engine
A nightly job (and a manually triggerable rebuild) computes, for **every day**
since the first transaction:
- value and quantity per position
- aggregates per account, asset class, currency, liquidity tier
- net and gross worth
- cumulative external capital flows

This writes to a `daily_snapshot` table. Reason: charts spanning ten years must
not refold the entire ledger on every request — on a Pi you notice. Snapshots
are a **cache, not the original**: `POST /api/admin/rebuild-snapshots` recreates
them completely at any time.

---

## 4. Metrics and analysis

### 4.1 The distinction that matters
There are **three notions of wealth**, and they are kept clearly separate everywhere:

| Notion | Contents | Used for |
|---|---|---|
| **Investable portfolio** | brokerage + crypto + metals + cash | allocation, return, rebalancing |
| **Gross worth** | + house + car | the full picture |
| **Net worth** | − mortgage | the number that actually counts |

This matters: if the house is 60 % of total wealth, an equity share of "18 % of
total wealth" is not an actionable figure. The allocation view therefore has a
switch between the three perspectives, defaulting to *investable portfolio*.

### 4.2 Return
- **TWR (time-weighted)** — chained daily returns, adjusted for deposits and
  withdrawals. Answers: *how good were my investments?* Comparable to benchmarks.
- **MWR / XIRR (money-weighted)** — internal rate of return across all capital
  flows. Answers: *what did this earn **me**?* Reflects the timing of contributions.
- Both for 1M / 3M / YTD / 1Y / 3Y / 5Y / since inception, in total, per account
  or per instrument. The scope is a selector on the returns view, and the
  per-instrument case is also served whole, as a ranking — a batch endpoint
  rather than one request per holding, because inception and the value series
  each re-scan the snapshot table.

  The ranking is deliberately *not* the unrealised P/L percentage the portfolio
  view already carries. That one compares a lot against what was paid for it and
  is therefore dominated by *when* it was bought; only a time-weighted figure is
  comparable between two holdings, or against a benchmark. Each row reports its
  own window, since a holding younger than the requested period cannot cover it.
- **Calendar years:** the same TWR cut by calendar year rather than by trailing
  window, with the benchmark alongside it. Each year is measured from the
  previous 31 December's close, so the years chain: multiplying them together
  reproduces the since-inception figure, and that identity is what makes the
  table checkable. A year clipped at either end — by inception, or by the last
  snapshot — is marked as partial rather than presented as an annual return.

  This is not a reversal of 4.5. Volatility and drawdown were dropped as
  decoration for a portfolio checked every few months; a year-by-year table is
  the granularity people actually narrate their own finances in, and it is
  derived from the same chained returns rather than a second set of numbers.
  MWR is deliberately absent from it: an annualised rate shaped by the timing of
  flows does not mean what a column of them read top-to-bottom would suggest.
- **Benchmark overlay:** a selectable reference (e.g. an MSCI World ETF) as a
  line in the chart, plus the question "what if every contribution had gone into
  X instead?" — highly informative and trivial to compute with the flows already
  present.

### 4.3 Attribution
The change in value over a period is decomposed into:
```
Δ wealth = deposits − withdrawals
         + market gains/losses
         + income (dividends, interest)
         − costs (fees, taxes, loan interest)
         + valuation adjustments (house/car)
         + FX effect
```
Rendered as a waterfall per month and per year. This is the view that yields the
most insight and that few off-the-shelf tools get right — above all the
separation of "did I get richer because I saved, or because the market ran?".

### 4.4 Structure and risk
- Allocation by asset class, account, region, currency, liquidity tier
  (donut + treemap + stacked area over time)
- **Target allocation & drift:** targets per class, deviation in pp and absolute,
  rebalancing proposal — including a *"purchases only"* mode (no selling; the
  next contribution is distributed across the underweight classes)
- **Concentration risk:** top-10 positions as a share, HHI concentration index,
  largest single-stock weight
- **ETF look-through:** optional, a region/sector breakdown maintained per ETF
  (entered by hand from the factsheet; it rarely changes). This reveals that a
  single share you hold directly also sits inside three of your ETFs.
- **Currency exposure** including the FX contribution to return

### 4.5 Cash flow and saving behaviour — dropped
Savings rate, dividend calendar and a running-cost view were specified here and
deliberately dropped: attribution (4.3) already separates contributions from
income from costs per period, which answers the same questions without a second
set of numbers to reconcile. Volatility and max drawdown went the same way — for
a portfolio checked every few months, a drawdown chart is decoration.

The heading stays so the section numbers below keep matching the citations in
the code.

### 4.6 Further worthwhile metrics
- **Real vs. nominal:** the wealth curve additionally adjusted for inflation
  (German CPI, annual maintenance is enough). Over ten years this is a very
  different chart.
- **Milestones:** the next round number, and time to reach it at the current
  savings rate and an assumed return
- **Coverage / runway:** investable portfolio ÷ annual expenses (if you record
  expenses roughly) — the classic FIRE metric, optional
- **Asset-class filter on returns:** the same global class filter the
  wealth and portfolio views use, applied to TWR/MWR. It narrows the
  eligible instruments once, so values, flows and inception all move
  together — a filter reaching the value series but not the flows would
  report contributions into excluded holdings as pure return. The
  benchmark overlay follows it, which is the point: comparing a whole
  portfolio (metals, crypto, cash) against MSCI World is not a
  comparison, comparing the equity sleeve against it is.

  It deliberately does *not* apply to attribution or tax. Attribution is
  an identity — its buckets must sum to the change in total net worth,
  and cash, loan interest and FX have no asset class. Tax hangs off
  annual portfolio-wide figures: the Sparerpauschbetrag and the §23
  Freigrenze are consumed by everything owned, not by a selection.

- **Tax-informational** (explicitly non-binding): usage of the annual saver's
  allowance, FIFO cost basis per position, unrealised P/L with an estimated tax
  charge on sale, a reminder about the January advance lump sum.

  Two regimes, kept apart because they behave differently:
  - **§20 EStG** (shares, ETFs, bonds, dividends, interest) — flat
    Abgeltungsteuer + Soli, holding period irrelevant, offset against the
    *Sparerpauschbetrag*, a real allowance where only the excess is taxed.
  - **§23 EStG** (crypto, physical precious metals; property at ten years)
    — **tax-free once held beyond the speculation period of one year**.
    Inside it, taxed at the *personal* income tax rate against a separate
    *Freigrenze*: a cliff, so reaching the limit makes the whole gain
    taxable, not just the excess.

  The regime comes from `instrument.asset_class`, overridable per
  instrument via `tax_treatment` — asset class cannot distinguish a
  physically-backed gold ETC (§23) from a swap-based one (§20), and
  guessing would be inventing a domain rule.

  Holding period is decided per FIFO lot against today's price, not by
  splitting a position's aggregate gain pro rata — those disagree
  whenever the lots were bought at different prices, which is the normal
  case for anyone buying monthly.

- **"If I sold everything now"**: one figure for the whole portfolio —
  value, cost basis, unrealised P/L, tax per regime and net proceeds —
  with positions listed most-tax-first. Computed regime-wide rather than
  position-by-position, because allowances, the Freigrenze and loss
  offsetting are all properties of the year's total. Each position's tax
  is its share of its regime's bill, so the rows sum to the headline
  figure and a position at a loss carries none.

- **Vorabpauschale**: recorded, not calculated — entered by hand into
  `vorabpauschale_entry`, same as CPI and the house index. The Basiszins
  is not the obstacle: the BMF publishes it annually under § 18 Abs. 4
  InvStG and it is one scalar per year. The gap is per-fund — the
  Teilfreistellung class (30% equity / 15% mixed / 0%) and whether the
  fund accumulates — which `instrument` does not model. The broker's
  January figure already has all of it applied. It matters because it is deemed §20 income
  debited in the first days of January and can consume the entire
  Sparerpauschbetrag before any sale does; an estimate that ignores it
  hands itself headroom that was already spent.
- **Data quality panel:** which valuation is how old, which price is stale, which
  position has no cost basis — prevents silent trust in outdated figures

---

## 5. Price data — which sources, with or without an API key

**Short answer:** for this use case, no API key is needed at all. An optional
free key only improves stability.

Design: a `PriceProvider` interface with a **fallback chain per instrument**.
Each instrument has an ordered list of sources; the first to return a plausible
value wins. Providers are swappable plugins — if a source disappears, that is a
config change, not a rebuild.

| Asset class | Primary source (keyless) | Fallback | Notes |
|---|---|---|---|
| ETFs, shares | **Stooq** CSV: `https://stooq.com/q/l/?s={ticker}&f=sd2t2ohlcv&h&e=csv` | Yahoo Finance endpoint (unofficial) | Stooq also serves full history (`/q/d/l/?s=...&i=d`) → **backfill without a key**. Mind the ticker convention (`.DE`, `.UK`, `.US`); the ISIN→ticker mapping is set once per instrument by hand. |
| Crypto (BTC) | **CoinGecko** `/api/v3/simple/price?ids=bitcoin&vs_currencies=eur` | Kraken/Bitstamp public ticker | Keyless: roughly 5–15 calls per minute. A free demo account raises this to a stable 30/min and 10,000 calls per month. History via `/coins/bitcoin/market_chart`. |
| Gold, silver | **Stooq** `xauusd`, `xagusd` | gold-api.com or goldprice.dev (both have keyless endpoints) | Spot in USD → converted via FX. Stooq serves history here too. |
| FX (USD/EUR etc.) | **Frankfurter** (`api.frankfurter.dev`, ECB reference rates, keyless) | ECB XML directly, Stooq `eurusd` | ECB rates are the clean reference for valuation purposes. |
| House price index | **Destatis GENESIS web service**, table 61262, quarterly | last known value is held | Free; the web service may require a one-off registration — fully automatic thereafter. Note: the CSV is not UTF-8. |
| Car value | no usable free API | — | Pure model, no fetching (see 3.3). |

**If you do want a key:** Alpha Vantage is too tight to serve as a fallback — the
free tier allows 25 requests per day. Twelve Data or Financial Modeling Prep
would be better choices, but with roughly 20 instruments fetched once a day you
do not need any of them.

**Rules for the price layer:**
1. **EOD is the default.** A job at 22:30 fetches closing prices. A manual
   refresh button covers the rest.
2. **Always persist.** Every fetched price lands in `price_point`. The
   application computes exclusively against its own database — external sources
   are fillers, not a runtime dependency.
3. **Plausibility check.** A daily move over 25 % or a price of 0 marks the value
   `suspect`; it is not adopted and a warning appears in the data quality panel.
4. **Be polite.** Sequential requests with a pause, a proper `User-Agent`, retry
   with backoff, cache results. At 20 instruments once a day, no source is
   remotely burdened.
5. **Never fetch prices in the UI request path.** The UI reads the database only.

---

## 6. Architecture

> **ADVISORY — not binding.** This chapter was written by someone who is not
> building the system. It is a starting point to argue with, not a requirement.
> The technical decisions belong to whoever implements this; where you have a
> better answer, take it and record the reasoning in `docs/adr/`.
>
> Binding within this chapter are only the *properties*, not the means:
> LAN-only reachability, offline-capable PWA, no credentials and no money
> movement, data that survives the application, and backups whose silent failure
> becomes visible.

### 6.1 One possible stack
```
┌─────────────────────────────────────────────┐
│ Browser / PWA (desktop, phone, tablet)      │
│  React + TypeScript + Vite                   │
│  TanStack Query (+ IndexedDB persister)      │
│  Recharts or uPlot · Tailwind                │
│  Workbox service worker (vite-plugin-pwa)    │
└──────────────────┬──────────────────────────┘
                   │ REST/JSON, bearer token
┌──────────────────┴──────────────────────────┐
│ Raspberry Pi 5 · Docker Compose (arm64)      │
│                                              │
│  api      FastAPI + SQLModel                 │
│           ├─ ledger & valuation engine       │
│           ├─ price providers (plugins)       │
│           ├─ snapshot job (APScheduler)      │
│           └─ OpenAPI /api/docs               │
│  db       SQLite (WAL) on SSD                │
│  web      Caddy (static frontend + TLS)      │
│  backup   nightly dump → NAS                 │
└─────────────────────────────────────────────┘
```

**Why FastAPI:** the auto-generated OpenAPI specification is the real prize — the
agent reads `/api/openapi.json` and knows which endpoints exist with which
fields, without further explanation. Pydantic validation supplies precise,
machine-readable errors on top. Both feed directly into the agent workflow.

**Why SQLite:** single user, a few thousand rows, backup is one file. Postgres
would be pure operational overhead here. Migrations still go through Alembic so
later model changes stay clean.

### 6.2 Offline and caching
The desired behaviour — *always load the latest data, otherwise show cached
values* — is exactly `stale-while-revalidate`:

- **TanStack Query with an IndexedDB persister:** on start the last state renders
  immediately from IndexedDB while a fetch runs against the Pi. If it succeeds
  the view updates; if it fails (away from home), the cache stands.
- **Service worker (Workbox):** app shell `CacheFirst`, API responses
  `NetworkFirst` with a short timeout (~2 s) so nothing hangs on the road.
- **Visible freshness:** a persistent status bar — *"as of 2026-08-12, 22:31 ·
  offline"*. Data older than 24 h gets a subtle tint. Never an empty screen, and
  never a stale number that looks fresh.
- **Snapshot endpoint:** `GET /api/snapshot/full` returns everything the
  dashboard needs in *one* request (aggregates plus reduced-resolution time
  series). Caching one request is more robust than caching fifteen.
- **Offline writes:** deliberately **not** supported. Writes are agent-driven and
  happen at home anyway. Forms disable themselves offline with a clear note —
  better than a sync queue with conflict logic needed once a year.

### 6.3 Remote access

**Decided: no additional remote access.** The application is reachable on the
home network only. Away from home the PWA runs in cache mode; for a live view
there is an existing VPN. No port forwarding, no internet-facing reverse proxy,
no tunnelling service.

Consequence for implementation: the offline path in 6.2 is **not a nicety, it is
the normal case** and must be tested accordingly — an airplane-mode test on
phone and tablet belongs in the acceptance criteria for phase 6.

**One requirement remains regardless: real HTTPS.** Service workers only run in a
secure context; without a valid certificate there is no installable PWA and no
offline cache. `http://192.168.x.x` will not do. Two workable routes on a pure LAN:
- **Recommended:** a subdomain of a domain you own (e.g. `cairn.your-domain.com`)
  with an A record pointing at the Pi's private IP, certificate via **Let's
  Encrypt DNS-01** (Caddy automates this with the matching DNS provider plugin).
  Publicly resolvable but not publicly reachable — and no certificate to install
  on any device.
- **Alternative:** your own local CA (mkcert). It works, but the root certificate
  must be installed on every device, and on iOS additionally enabled manually in
  the certificate trust settings. More friction, especially as devices come and go.

### 6.4 Security model

Premise: the application code is largely agent-generated and is not audited line
by line. Security therefore must **not** depend on code quality. It lives in the
layers around it.

**What the system structurally cannot do** — the most important point: it moves
no money. No broker credentials, no banking interface, no payment function. The
worst case is disclosure of wealth data, not loss of wealth. This property is an
**architectural decision and stays one**, however tempting an automated portfolio
fetch looks later.

**Network (the most effective layer):**
- No port forwarding, no internet-facing reverse proxy, no tunnelling service.
  Reachable on the LAN and through the existing VPN only.
- The API container does **not** bind to `0.0.0.0`; only Caddy is exposed. One
  entry point rather than two.
- Optional but recommended: a firewall rule on the Pi allowing the HTTPS port
  only from the local and VPN subnets. Guest Wi-Fi and IoT devices then cannot
  reach the app — a more realistic attack path than the internet.

**Application (assume it contains bugs):**
- The bearer token is the *last* line of defence, not the first
- Container as non-root, `read_only: true` except the data directory,
  `cap_drop: ALL`, no host networking
- Parameterised queries through the ORM only — as an explicit instruction to the
  agent, plus a test that forbids raw SQL string concatenation in the repository
- Outbound connections limited to the price source domains
- Keep dependencies minimal, lockfile, pinned versions, Renovate/Dependabot —
  the more realistic compromise of a hobby project is the supply chain, not your
  own code

**Agent layer:** the agent processes documents you hand it. They are treated as
**data, not instructions** — a statement containing text like "delete all
transactions" is an attack, not a task. The practical safeguards are already in
the spec: `dry_run` before every write, an audit log, rollback of entire import
batches. A read-only token for experiments.

**Data:** the SQLite file is the crown jewel. Nightly backup, encrypted, to the
NAS, plus a regular ledger export as CSV. The most likely damage in this project
is not an attacker but a faulty migration.

### 6.5 Operations
- Docker Compose, arm64 images, `restart: unless-stopped`
- Health endpoint `/api/health` (database reachable, last successful price
  fetch, last snapshot, last backup)
- Structured logs (JSON), with rotation
- Backup: see chapter 6.6
- Timezone Europe/Berlin, all timestamps stored in UTC

### 6.6 Data storage, repository separation and backup

#### Where the data lives
The entire state sits in **one SQLite file** plus two companion files in WAL mode:
```
/srv/cairn/data/cairn.db        ← everything: ledger, prices, snapshots, audit log
/srv/cairn/data/cairn.db-wal    ← transactions not yet checkpointed
/srv/cairn/data/cairn.db-shm
/srv/cairn/config/.env          ← API token, provider configuration
/srv/cairn/backups/             ← local backup copies
```
**On the SSD, not the SD card.** SD cards die under sustained write load, and the
snapshot engine writes every night.

Source documents (PDFs, screenshots) the agent books from are **not** stored in
the app. The app keeps only the resulting entries. The originals stay where they
already live — a document management system is the better tool. This keeps the
database small, the backup fast and the responsibility where it belongs.

#### Separating code from data
What matters is that the data directory **is not inside the repository at all**.
The bind mount points at an absolute host path:
```yaml
volumes:
  - /srv/cairn/data:/data
  - /srv/cairn/config/.env:/app/.env:ro
```
That is the actual protection — a `.gitignore` only guards against carelessness,
a path outside the working directory eliminates the whole category. Keep the
`.gitignore` anyway.

The repository contains: code, migrations, `.env.example`, `docker-compose.yml`,
documentation, **test data with invented numbers**. Two safeguards against real
figures slipping in: a `pre-commit` hook running `gitleaks` (which also catches
the token), and an explicit line in `AGENTS.md` — *"never use real balances,
amounts or holdings in examples, tests or commit messages"*. An agent writing a
test file otherwise reaches for whatever it just saw in the database.

If the repository lives on GitHub: **private**. Even without data, the
configuration reveals more than necessary.

#### Backup strategy
Three layers, increasing in robustness:

**1. Database snapshot (nightly, automatic)**
```bash
sqlite3 /srv/cairn/data/cairn.db ".backup '/srv/cairn/backups/cairn-$(date +%F).db'"
sqlite3 /srv/cairn/backups/cairn-$(date +%F).db "PRAGMA integrity_check;"
```
`.backup` rather than `cp` is not optional: copying a live WAL database will very
likely yield an inconsistent and, when it matters, worthless backup. Then
`integrity_check` — a backup that was never verified is a guess.

**2. Logical export (nightly, automatic)**
`GET /api/export/full` writes all accounts, instruments, transactions, valuation
anchors and loan parameters as CSV and JSON. The difference from the database
backup is essential: the export survives **schema changes and the application
itself**. If the project is replaced in three years, or a migration wrecks the
ledger, this file is the way out. Price data need not be exported — it can be
refetched at any time.

**3. Offsite (3-2-1)**
- **Pi → NAS:** rsync or a share mount as target
- **NAS → offsite, encrypted:** `restic` or `rclone crypt` into cloud storage.
  The file contains your complete financial picture; unencrypted it has no
  business sitting in someone else's infrastructure.
- **Retention:** 7 daily, 4 weekly, 12 monthly. At this file size that costs
  effectively nothing, and slow-creeping data corruption often surfaces only
  weeks later — at which point you need an old state.

**Restore.** Must be documented *and* actually rehearsed once, in
`docs/disaster-recovery.md`. Because the application is fully reproducible from
the repository, "the Pi is dead" reduces to: new card, Docker, restore the file.
Realistically half an hour. The API token therefore belongs in your password
manager, not only in the `.env` on the Pi — otherwise the one file that is not in
the backup is exactly the one missing when it counts.

**Visibility.** `/api/health` reports the timestamp and result of the last
backup; the data quality panel warns when the last successful backup is older
than 48 hours. A silently failing cron job is the default outcome for home
server backups.

---

## 7. API design for the agent

This is the part that determines everyday usefulness. Goal: hand an agent a
statement as a PDF or screenshot, say "book this", and have it happen correctly,
traceably and without duplicates.

### 7.1 Endpoints (excerpt)

**Read**
```
GET  /api/health
GET  /api/snapshot/full?as_of=YYYY-MM-DD
GET  /api/accounts
GET  /api/instruments?search=
GET  /api/positions?account_id=&group_by=instrument|account
GET  /api/transactions?from=&to=&account_id=&limit=&cursor=
GET  /api/timeseries/networth?from=&to=&granularity=day|week|month
GET  /api/allocation?dimension=asset_class|account|region|currency|liquidity&scope=investable|gross|net
GET  /api/performance?scope=&period=&method=twr|mwr
GET  /api/data-quality        # stale prices, missing cost basis, old valuations
GET  /api/export/full
```

**Write**
```
POST   /api/instruments
POST   /api/accounts
POST   /api/transactions              # single
POST   /api/transactions/bulk         # batch, supports dry_run
PATCH  /api/transactions/{id}
DELETE /api/transactions/{id}
POST   /api/valuations                # anchors for house/car
POST   /api/prices/refresh
POST   /api/prices/backfill
POST   /api/admin/rebuild-snapshots
POST   /api/reconcile                 # target/actual comparison, see 7.4
DELETE /api/import-batches/{id}       # roll back an entire import
POST   /api/import-batches/{id}/supersede
```

### 7.2 Idempotency and safety nets
- **`external_id`** per transaction (a broker reference, or a hash of
  date+ISIN+quantity+price). Re-sending the same `external_id` returns `200` with
  the existing record instead of creating a duplicate. This is the single most
  important measure: agents like to send twice.
- **`import_batch_id`** for every import run. A whole batch is reversible with
  one call: `DELETE /api/import-batches/{id}`. A failed agent run is therefore
  inconsequential.
- **`dry_run: true`** on all bulk endpoints: returns the planned changes
  including resulting holdings and warnings, and writes nothing. The standard
  workflow is dry run → you look → commit.
- **Validation in plain language:** selling more than held, buying before the
  account existed, a price more than 30 % away from that day's market price, an
  unknown ISIN, a future date → `422` with the field path, actual value,
  expectation and a suggested fix. Error messages are UI for the agent.
- **Audit log:** every write with timestamp, source (`agent`/`manual`) and
  payload hash. In the UI, a change view: *"what changed since yesterday"*.

### 7.3 Example payload
```jsonc
POST /api/transactions/bulk
{
  "dry_run": true,
  "import_batch_label": "Portfolio A annual statement 2025",
  "transactions": [
    {
      "external_id": "portfolioA-2025-03-14-IE00B4L5Y983-buy-1",
      "date": "2025-03-14",
      "type": "BUY",
      "account": "portfolio-a",
      "instrument": { "isin": "IE00B4L5Y983", "ticker": "EUNL.DE" },
      "quantity": 12.5,
      "price": 92.34,
      "currency": "EUR",
      "fees": 1.50,
      "note": "savings plan execution",
      "source": "agent"
    }
  ]
}
```
Dry-run response: per row `would_create | would_update | duplicate_skipped`, plus
the resulting holdings, detected warnings and a diff against the current state.

### 7.4 Reconcile — the underrated endpoint
You hand the agent a current statement. It sends the **actual holdings**:
```jsonc
POST /api/reconcile
{ "account": "portfolio-a", "as_of": "2026-08-12",
  "holdings": [ { "isin": "IE00B4L5Y983", "quantity": 412.3 } ] }
```
The app compares against the holdings computed from the ledger and reports
differences. This surfaces a missing savings plan execution, split or scrip
dividend without you ever recounting a position by hand. Optionally it proposes
correcting entries.

### 7.5 Agent documentation
In the repository:
- `AGENTS.md` / `CLAUDE.md` — context, conventions, "this is how you book a
  statement", example payloads, common pitfalls (partial fills, foreign currency
  purchases, distributions with withholding tax, in-kind transfers)
- `docs/agent-workflows.md` — worked scenarios: import an annual statement ·
  book a single order · create new instruments · calibrate the car value · book
  a mortgage overpayment
- `docs/data-model.md` — ERD and field semantics

**The MCP server is the agent's entry point** (`mcp_server/`, see its README):
a thin translation layer that turns the same endpoints into native tool calls
with schema validation, `dry_run` included. It runs locally over stdio and talks
to the Pi over the LAN like any other client. A `scripts/cairn` shell wrapper was
specified here originally and deliberately dropped — it would have been a third
way to do what the API and the MCP tools already do, with its own drift.

### 7.6 Authentication
A static bearer token in `.env`, checked on all `/api` routes; the UI obtains it
through a single sign-in stored in an HttpOnly cookie. No OAuth, no user
management overhead. A separate read-only token for experiments is possible.

---

## 8. Interface

> **ADVISORY except where noted.** The page structure and visual direction are a
> proposal. Binding: the three wealth perspectives must stay distinguishable
> everywhere (4.1), estimates must never render like market prices, data
> freshness must be visible, and the i18n and theme requirements in 8.3 —
> German default, English switchable, light/dark/system — are requirements.
> How you achieve them is yours.

### 8.1 Page structure

The UI is **read-mostly by construction**. Data arrives through the agent API
every few months (7.), so the interface optimises for looking and understanding,
not for entering. Exactly one write survives in the UI — the cash-balance
statement — because it is the one figure worth correcting on the spot.

Five sections, which is also what a mobile tab bar holds:

| Section | Contents |
|---|---|
| **Overview** (`/`) | net worth headline with Δ and sparkline, asset-mix donut, next-milestone arc, this-month attribution summary, freshness strip (price fetch · snapshot · backup · data-quality issues), cash-balance action |
| **Wealth** (`/wealth`) | net-worth curve (nominal/real, period selector), asset-class mix over time, time-travel replay, milestone journey — all scoped by the asset-class filter |
| **Portfolio** (`/portfolio`) | asset-class distribution, instrument distribution with unrealised P/L, region and sector look-through, target vs. actual drift, physical assets and loans |
| **Performance** (`/performance`) | tabs: returns (TWR/MWR, benchmark overlay) · attribution (per-period composition + cumulative waterfall) · tax |
| **Data** (`/data`) | read-only tables: ledger · positions · accounts · instruments. Verification surface for what the agent booked, never a form |

Settings (language, theme, export) sits behind a header icon rather than in the
primary navigation.

**The asset-class filter** is the one piece of global state worth naming: a chip
row that includes or excludes each asset class, shared across Wealth and
Portfolio and persisted. It exists because a house dominates a net-worth chart
so completely that everything else becomes a flat line — the question "how are
my equities and crypto doing, ignoring the property" needs an answer, and it
changes the milestone dates too.

### 8.2 Visual direction
Personal rather than institutional — this is one person's wealth, not a trading
desk. Dark is the primary theme (light remains available and functional):
near-black with a blue cast, translucent panels, soft glow on the elements that
matter, gradient-filled charts. Playful is allowed; cluttered is not. Data still
dominates.

- **Layout:** cards on an ambient background, max width ~1150 px, generous
  spacing; one radial gradient behind the whole app rather than per-page
  decoration
- **Typography:** Inter Variable, self-hosted; **tabular figures**
  (`font-variant-numeric: tabular-nums`) everywhere numbers stack — the single
  detail that makes a financial UI read as trustworthy. Hero figures large and
  tight-tracked
- **Colour:** one accent (cyan), a fixed eight-colour categorical palette keyed
  to asset class so a chart, a legend dot and a table marker can never drift
  apart; green/red reserved strictly for sign — plus ▲/▼ so meaning does not
  rest on colour alone
- **Charts:** gradient area fills, thin strokes, no 3D; restrained axes; glass
  tooltips with exact values and dates; period switcher as a segmented control.
  Debt renders below the zero line rather than as a positive slice
- **Motion:** CSS and two small rAF hooks, no animation library. Numbers count
  up, arcs sweep, the replay scrubs. All of it yields to
  `prefers-reduced-motion`, and none of it is load-bearing for meaning
- **Number format:** locale-aware (see 8.3), thousands separators; large amounts
  compacted on mobile
- **Mobile:** first-class, not an afterthought — bottom tab bar, single column,
  touch-friendly charts, tables scroll inside their card; PWA icon, splash
  screen, `display: standalone`, theme colour

### 8.3 Internationalisation and theme

**Languages:** German (default) and English, switchable in settings without a reload.

**Implementation:** `react-i18next` with JSON resources (`de.json`, `en.json`)
split into namespaces (`common`, `dashboard`, `assets`, `settings`, `errors`).
The selected language is stored server-side in a `settings` table **and** mirrored
in `localStorage` — otherwise the wrong language flashes on every start, and
offline there would be none at all.

**Four rules bilingual apps typically fail on:**

1. **No translated values in the database.** Asset classes, transaction types and
   valuation modes are stored as English keys (`EQUITY`, `BUY`) and translated
   only for display. Write "Aktie" into the database and the language switch is
   gone.
2. **The API stays English-only.** Field names, enums and error codes are
   English — the agent works against a stable interface, not a translation.
   Errors therefore return `{"code": "sell_exceeds_holding", "params": {...}}`
   rather than a finished sentence; the frontend translates. Side effect: error
   messages become bilingual for free, without the backend caring.
3. **Formatting through `Intl`, never hardcoded.**
   `Intl.NumberFormat(locale, {style:'currency', currency:'EUR'})` and
   `Intl.DateTimeFormat`. The **currency stays EUR** — only the notation follows
   the language: `1.234,56 €` versus `€1,234.56`. For English use `en-GB`, not
   `en-US`: a date like `03/08/2026` would otherwise be either 3 August or
   8 March depending on the reader.
4. **Do not forget the charts.** Axis labels, tooltips, legends and period
   switches go through i18n and the locale formatters too. This is where German
   remnants survive in the English UI.

Free text you enter yourself (notes, account names) is not translated. CI runs a
**key parity** test between `de.json` and `en.json` — missing translations break
the build rather than silently falling back to the key.

**Theme:** light / dark / system, also in settings. Implemented with CSS
variables and a `data-theme` attribute on the root element, system detection via
`prefers-color-scheme`. Two details for the PWA:
- A tiny inline script in `index.html` applies the theme from `localStorage`
  **before** React loads — otherwise the light surface flashes on every cold start.
- `<meta name="theme-color">` changes with the theme so the status bar and splash
  screen match when installed.

Two chart palettes are defined (light/dark) — the same colour values do not work
on both backgrounds, contrast inverts.

---

## 9. Data model (sketch)

> **ADVISORY.** A sketch to show the intended shape, not a schema to implement.
> The entities and the relationships between them follow from chapter 2 and are
> binding; table layout, naming, keys, types and normalisation are yours. Produce
> your own proposal in `docs/data-model.md` before writing code.
>
> Two constraints survive any schema you choose: money is never a float, and
> holdings and values are always derived from transactions rather than stored as
> the source of truth.

```sql
account(id, name, type, currency, opened_at, closed_at, institution,
        verified_from, sort_order, archived)

instrument(id, name, isin, wkn, ticker, asset_class, valuation_mode, currency,
           region, sector, liquidity_tier, ter_pct, fine_weight_g, tags_json, notes)

price_source(id, instrument_id, provider, provider_symbol, priority, enabled)

price_point(instrument_id, date, close, currency, provider, quality,
            PRIMARY KEY(instrument_id, date))

fx_rate(base, quote, date, rate, PRIMARY KEY(base, quote, date))

txn(id, external_id UNIQUE, import_batch_id, date, date_precision, type,
    account_id, instrument_id, quantity, price, price_mode, currency, fx_rate,
    fees, tax, amount_eur, counter_account_id, provisional, note, source,
    created_at, updated_at)

valuation_anchor(id, instrument_id, date, value_eur, method, confidence, source, note)

loan(id, account_id, principal, rate_pct, start_date, fixed_until,
     monthly_payment, payment_day, extra_repayment_allowance_pct)

daily_snapshot(date, scope_type, scope_id, quantity, value_eur, cost_basis_eur,
               PRIMARY KEY(date, scope_type, scope_id))

target_allocation(dimension, key, target_pct, tolerance_pp)

setting(key, value_json)

audit_log(id, ts, actor, action, entity, entity_id, payload_hash, diff_json)
```

Amounts as `DECIMAL` or integer cents, **never floats** for money. Quantities as
`Decimal` with 8 decimal places (BTC).

---

## 10. Delivery in phases

Important for handing this to an agent: **one phase = one complete, running,
tested state.** No big bang.

| Phase | Contents | Outcome |
|---|---|---|
| **1 — Foundation** | data model including the maturity fields from 2.5, migrations, CRUD for accounts/instruments/transactions, opening balances, holdings calculation, tests for the ledger logic | API stands, usable via curl |
| **2 — Prices & history** | provider plugins, price backfill, FX, snapshot engine, job scheduler | the net worth time series exists |
| **3 — Frontend v1** | dashboard, performance, allocation, positions; design system, dark mode | usable in a browser |
| **4 — Agent layer** | bulk import, dry run, idempotency, reconcile, supersede of opening balances, `AGENTS.md`, example workflows | booking and backfilling by agent works |
| **5 — Physical assets** | house anchors and index, car model, loan schedule, LTV, assets page | net worth complete |
| **6 — PWA & offline** | service worker, IndexedDB persistence, freshness indicator, icons, mobile polish | usable away from home |
| **7 — Analytics** | TWR/MWR, attribution, benchmark, target allocation, inflation, data quality panel | full insight |
| **8 — Extras** | MCP server, tax view, look-through, milestones, export | optional |

Additionally specified for phase 1: a **golden test dataset** — an invented
portfolio with a purchase, partial sale, split, dividend, foreign currency
purchase, in-kind transfer and a provisional opening balance later superseded by
real history, with expected holdings and metrics. The agent can then verify its
own ledger logic, and regressions surface immediately later. This is the single
most effective quality measure in the project.

---

## 11. Decisions taken

| # | Topic | Decision | Impact |
|---|---|---|---|
| 1 | **History depth** | Start with provisional opening balances; history is backfilled incrementally and retroactively | Chapter 2.5 is therefore **mandatory from phase 1**: `OPENING_BALANCE`, supersede, `date_precision`, `price_mode: auto`, `verified_from` |
| 2 | **Car** | Pure model, no manual lookups | 3.3; displayed clearly as an estimate, the anchor stays as an optional hook |
| 3 | **House value** | Automatic index tracking (Destatis 61262) from the purchase price | 3.4; requires the index job, an uncertainty band, its own attribution bar and the "at acquisition cost" toggle |
| 4 | **House purchase costs** | Not in the cost basis — booked as a `FEE` against cash | 3.4 |
| 5 | **Cash** | Balance statements from screenshots only, **no** transfers, no individual entries | 3.6; the transfer heuristic is dropped entirely. Portfolio inflows are derived from securities transactions (settlement account), savings rate as a residual |
| 6 | **Remote access** | No additional remote access — cache mode, existing VPN when needed | 6.3; the offline path becomes the normal case and is acceptance-relevant. HTTPS remains mandatory (service workers) |
| 7 | **Language & theme** | DE (default) / EN switchable, light/dark/system in settings | 8.3; API and database values stay English, translation only in presentation |
| 8 | **Name** | `Cairn`, repository `cairn` | package, container, hostname and PWA manifest kept consistent |

### Still to settle
- **Index series for the house:** national, state or district type? Pick it with
  the agent on the first fetch; it is one configuration line.
