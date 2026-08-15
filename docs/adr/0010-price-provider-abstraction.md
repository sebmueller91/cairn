# 0010 — Price provider abstraction

**Status:** proposed
**Date:** 2026-08-15

## Context
Keyless public price sources (Stooq, CoinGecko, Frankfurter, Destatis) with
per-asset-class fallback chains. Sources will occasionally break or change
shape; swapping one out must be a config change, not a code change (spec 5).

## Options considered
Accepting spec's `PriceProvider` interface + fallback chain design without a
real alternative — it's the standard adapter pattern applied correctly to
this problem. The only decision worth recording is the exact contract shape.

## Decision
A `PriceProvider` protocol: `fetch(symbol: str, date_range: DateRange) ->
list[PricePoint]`. Each source (Stooq, CoinGecko, Frankfurter, Destatis,
Kraken-as-fallback) is a small adapter class registered by name in a
provider registry. The existing `price_source(instrument_id, provider,
provider_symbol, priority, enabled)` table drives the fetch job: iterate
providers in priority order per instrument, first plausible result wins
(plausibility per spec 5 rule 3: no >25% daily move, no zero price). Adding
or disabling a source is a row change in `price_source`, never a deploy.

## Rationale
Nothing to argue with here — the spec's design already achieves the stated
goal cleanly. Recording it as an ADR mainly to pin the exact interface shape
so every adapter is genuinely interchangeable (same method signature, same
return type) rather than each provider growing its own bespoke calling
convention over time.

## Consequences
Makes easy: a broken source (Stooq changes its CSV format) is contained to
one adapter class plus, if needed, a priority reorder in data — never
touches the fetch job or the rest of the app. Makes hard: nothing new beyond
what the spec already accepted — this is the extra small discipline of
writing every adapter against the same protocol even when a source's native
API doesn't map onto it cleanly (e.g. Destatis's non-UTF-8 quarterly CSV
needs its own parsing but still returns the same `PricePoint` shape).
