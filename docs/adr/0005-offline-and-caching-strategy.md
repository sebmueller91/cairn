# 0005 — Offline and caching strategy

**Status:** accepted
**Date:** 2026-08-15

## Context
LAN-only reachability (ADR-adjacent decision already taken in spec 6.3) means
offline is the *normal* case away from home, not a fallback path. Must never
show an empty screen, never show a stale number that looks fresh, and must
never let a write silently vanish when offline.

## Options considered
Largely accepting spec 6.2 as proposed; the decisions worth pinning down are
granularity of what's cached, how staleness is computed, and what a service
worker is allowed to touch.

## Decision
- **What's cached:** every GET query result, keyed by TanStack Query's query
  key, persisted to IndexedDB via a query-client persister. No hand-built
  cache — the query cache *is* the offline cache.
- **Granularity:** per-endpoint-plus-params, which is naturally coarse
  (dozens of distinct queries in the whole app, not thousands) — no custom
  eviction policy needed. No hard client-side TTL; a `buster` string bumped
  on breaking API/schema changes is the only thing that invalidates the
  persisted cache outright.
- **Query keys are time-invariant.** A rolling window bound (`from=` for the
  last 14 days, 180 days, a year) is resolved inside the `queryFn` at fetch
  time and never appears in the key; the midnight rollover that would
  otherwise motivate putting it there comes from a `staleTime` clamped at
  the next *local* midnight instead. Corollary of the bullet above: because
  the key is the address of the persisted entry, a key that changes on a
  timer does not make the cache stale, it makes it unreachable — the entry
  written yesterday is still in IndexedDB, under a key nothing will ever ask
  for again. Bump the `buster` when the key space changes, not only when a
  response shape does.
- **Staleness surfaced:** a global banner reads the oldest `dataUpdatedAt`
  across currently-mounted queries — *"as of 2026-08-12, 22:31 · offline"* —
  plus the 24h tint the spec specifies.
- **Service worker:** Workbox, `CacheFirst` for the app shell, `NetworkFirst`
  (~2s timeout) for `GET /api/*`, and explicit **no interception of
  non-GET requests** — POST/PATCH/DELETE always pass straight through to the
  network or fail visibly, never get silently "cached" as if they succeeded.
- **Offline writes:** not supported, per spec — all mutating controls disable
  with an explanatory note when `navigator.onLine` (backed by an actual
  reachability check, not just the browser flag) is false.

## Rationale
The one addition beyond spec 6.2 worth calling out explicitly is the
non-GET passthrough rule. A service worker that caches or queues writes by
default is how "offline-capable" quietly turns into "offline writes with an
undocumented sync queue" — exactly the complexity spec deliberately declines
("a sync queue with conflict logic needed once a year"). Making the
passthrough explicit here means it's a design decision under test, not an
accidental Workbox default.

## Consequences
Makes easy: the entire offline story rides on one already-necessary
dependency (TanStack Query) plus one well-trodden Workbox recipe — nothing
bespoke to maintain. Makes hard: forms need an explicit online-check gate
rather than "just submit and see" — a small amount of repeated UI logic
across every mutating form, worth extracting into one shared hook early.

The sharper edge, learned twice: making the query cache *be* the offline
cache means every ordinary query-cache habit is now an offline-behaviour
decision. `gcTime`, `shouldDehydrateQuery` and the shape of a query key each
look like local tuning and each silently decide whether there is anything to
show on a train. None of them announce themselves — the app is perfectly
correct at home either way, and only fails where it cannot be observed. That
is why `lib/queryState.ts` and `lib/persister.ts` carry the reasoning inline
rather than deferring to this ADR.
