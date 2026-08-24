# Cairn — data model proposal

Companion to spec chapter 9 (advisory sketch) and chapter 2 (binding domain
model). Table layout, naming and types below are the proposal for phase 1;
the entities and relationships come from spec ch. 2 and are not up for
debate. See ADR 0003 for the derived-data boundary this schema enforces.

## Storage of money and quantities

SQLite has no native arbitrary-precision decimal type, and SQLAlchemy's
stock `Numeric` type can silently degrade to `REAL` (float) on SQLite
depending on driver behaviour — a real way to violate the no-floats rule
without noticing. Concretely: a custom `Decimal` `TypeDecorator` stores
every money/quantity column as `TEXT` (Python `str(Decimal(...))`) and
parses back via `Decimal(text)`. Two logical types built on this:

- **`Money`** — quantized to 2 decimal places (EUR minor unit). Used for all
  `*_eur` columns.
- **`Quantity`** — up to 8 decimal places, unquantized (BTC-precision,
  fractional shares). Used for `quantity`, `fine_weight_g`.

Native-currency `price`/`amount` fields on `txn` are stored as `Quantity`
(not `Money`) since a crypto price can carry more than 2 decimals.

## Tables

```sql
account(
  id, name, type,                 -- BROKERAGE|CRYPTO_WALLET|PHYSICAL_STORAGE|REAL_ESTATE|VEHICLE|LOAN|CASH
  currency,                       -- settlement/display currency; does NOT constrain instrument.currency (see ambiguity c)
  opened_at, closed_at, institution,
  verified_from,                  -- TWR/IRR computed only from here onward (spec 2.5)
  sort_order, archived
)

instrument(
  id, name, isin, wkn, ticker,
  asset_class,                    -- EQUITY|BOND|COMMODITY|CRYPTO|REAL_ESTATE|VEHICLE|CASH|LIABILITY
  valuation_mode,                 -- MARKET|ANCHORED|MODELED|AMORTIZING_LIABILITY|NOMINAL
  currency, region, sector, liquidity_tier, ter_pct,
  fine_weight_g,                  -- metals only
  tax_treatment,                  -- CAPITAL_GAINS|PRIVATE_SALE|NONE, NULL = derive from asset_class
  valuation_config_json,          -- MODELED/ANCHORED parameters, see ambiguity (b)
  tags_json, notes
)

-- The advance lump sum the broker actually debited, entered by hand —
-- it needs the BMF Basiszins and per-fund Teilfreistellung, which this
-- app cannot fetch (same as cpi_index_point). `year` is the year it
-- counts against the saver's allowance, i.e. the year it was debited:
-- the Vorabpauschale accruing on 31 Dec N flows on the first working
-- day of N+1 and so eats the N+1 allowance.
vorabpauschale_entry(year PRIMARY KEY, amount_eur, note, updated_at)

price_source(id, instrument_id, provider, provider_symbol, priority, enabled,
             last_fetch_at, last_error)

price_point(instrument_id, date, close, currency, provider, quality, fetched_at,
            PRIMARY KEY(instrument_id, date))

fx_rate(currency, date, eur_rate,           -- 1 unit of `currency` = eur_rate EUR; EUR/EUR = 1
        PRIMARY KEY(currency, date))        -- simplified from spec's base/quote pair, see ambiguity (a)

txn(
  id, external_id UNIQUE, import_batch_id NOT NULL,
  date, date_precision,           -- day|month|quarter|year
  type,                           -- BUY|SELL|DIVIDEND|INTEREST|FEE|TAX|DEPOSIT|WITHDRAWAL|TRANSFER|SPLIT|VALUATION|OPENING_BALANCE|BALANCE_STATEMENT|LOAN_PAYMENT|EXTRA_REPAYMENT
  account_id, instrument_id NULLABLE,
  quantity, price, price_mode,    -- exact|auto
  currency, fx_rate, fees, tax,
  amount_eur,
  counter_account_id NULLABLE,    -- TRANSFER's destination account, see ambiguity (e)
  provisional,                    -- OPENING_BALANCE only
  voided_at NULLABLE, voided_by_batch_id NULLABLE,   -- supersede outcome, never a hard delete
  note, source,                   -- manual|agent|import
  created_at, updated_at
)

account_snapshot_watermark(account_id, dirty_from_date)   -- ADR 0003 incremental rebuild

valuation_anchor(id, instrument_id, date, value_eur, method, confidence, source, note)

loan(id, account_id, principal, rate_pct, start_date, fixed_until,
     monthly_payment, payment_day, extra_repayment_allowance_pct)

daily_snapshot(date, scope_type, scope_id, quantity, value_eur, cost_basis_eur,
               PRIMARY KEY(date, scope_type, scope_id))     -- cache only, see ADR 0003

target_allocation(dimension, key, target_pct, tolerance_pp, PRIMARY KEY(dimension, key))

setting(key, value_json, PRIMARY KEY(key))

audit_log(id, ts, actor, action, entity, entity_id, payload_hash, diff_json)
```

**Not a table:** current positions/holdings. Computed live from `txn` per
ADR 0003 — `GROUP BY account_id, instrument_id` with quantity/cost-basis
running sums, cheap enough at this data volume to never cache.

## Invariants that must always hold

1. **No floats** anywhere in `Money`/`Quantity` columns — enforced by the
   `TypeDecorator`, not by convention.
2. **Holdings are never written directly** — only `GROUP BY` over `txn`
   produces them (spec's central rule).
3. **`daily_snapshot` is bit-for-bit reproducible** from `txn` + `price_point`
   + `fx_rate` + `valuation_anchor` + `loan` via a full rebuild, always.
   `account_snapshot_watermark` only controls *how much* of the rebuild runs
   incrementally, never *whether* the result is correct.
4. **Every `txn` belongs to exactly one `import_batch_id`**, including a
   single manual entry (a batch of one) — this is what makes `DELETE
   /api/import-batches/{id}` a uniform rollback primitive rather than a
   special case for bulk imports only.
5. **`external_id` is globally unique.** A repeat with an identical payload
   hash is a no-op (`200`, existing row). A repeat with a *different*
   payload under the same `external_id` is a `409` conflict, never a silent
   overwrite — a real correction goes through `PATCH`, not through replaying
   an import. (See ambiguity (a) below — this is my proposed default, not
   yet confirmed against your intent.)
6. **`txn` rows are mutated in place by `PATCH`**; the audit trail of what
   changed lives in `audit_log.diff_json`, not as multiple ledger rows.
   `voided_at`/`voided_by_batch_id` exist only for the supersede workflow
   (spec 2.5), which is a distinct, narrower operation from a general edit.
7. **A `SPLIT` never rewrites historical `txn` rows.** It's applied as a
   multiplier during position/cost-basis computation to every `txn` for
   that instrument dated before the split date — the ledger records events,
   the aggregation interprets them.

## Decisions confirmed (2026-08-15)

**`external_id` collision, different payload → `409 conflict`.** A repeat
with an identical payload hash is a no-op (`200`, existing row); a repeat
with different content under the same `external_id` is rejected outright.
Corrections go through `PATCH`, never through replaying an import with
different numbers.

**Car/house valuation parameters → `instrument.valuation_config_json`.**
Not a separate `instrument_valuation_config` table. These parameters are set
once at creation and rarely touched, so the JSON blob costs no migration per
new valuation-mode parameter and the schema-level-validation loss is
accepted as the trade-off.

## Still open, deciding unilaterally unless you object

**`account.currency` vs. `instrument.currency`.** Treating `account.currency`
as informational/settlement-only — a `BROKERAGE` account can hold
instruments in several currencies regardless of its own `currency` field.
Proceeding on this basis; flag if `account.currency` was meant to constrain
what it can hold.

**`TRANSFER` shape.** One `txn` row (`account_id` = source,
`counter_account_id` = destination), not two linked rows. Consequence baked
into every account-transactions query from phase 1: "all transactions for
account X" must match on *either* column, not just `account_id`.

**Cash interpolation/bridge (spec 3.6) is a real algorithm, not a lookup.**
Needed as early as phase 1–2 for the net-worth curve to include cash
accounts at all, even though spec discusses it under cash flow (ch. 4,
phase 7 in the original phasing). The revised phase plan pulls the
*mechanism* into phase 2, leaving the *reporting UI* (savings-rate display)
in phase 7.
