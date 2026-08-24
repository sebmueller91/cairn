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
