import { get, set, del } from "idb-keyval";
import { createAsyncStoragePersister } from "@tanstack/query-async-storage-persister";
import {
  persistQueryClientRestore,
  persistQueryClientSubscribe,
} from "@tanstack/react-query-persist-client";
import type { QueryClient } from "@tanstack/react-query";

// IndexedDB, not localStorage: query results can be sizeable (a decade of
// snapshot points) and localStorage's ~5-10MB synchronous-only quota is
// the wrong tool for this even before considering that idb-keyval's API
// is async and doesn't block the main thread the way localStorage does.
const idbStorage = {
  getItem: async (key: string) => (await get(key)) ?? null,
  setItem: async (key: string, value: string) => set(key, value),
  removeItem: async (key: string) => del(key),
};

// Bump this when old persisted entries would be wrong to *render* or
// impossible to *reach*:
//
//   - a schema/API change, e.g. a renamed field a cached response still
//     has the old name for; or
//   - a change to the query key space, which leaves the entries written
//     under the old keys stranded — nothing reads them, and with
//     `gcTime: Infinity` (main.tsx) nothing evicts them either.
//
// "3" is the second kind: the rolling `from` bounds came out of four query
// keys, so every per-calendar-day key set accumulated since is now dead
// weight. Not tied to app version generally; only these two cases need it
// (ADR 0005).
const CACHE_BUSTER = "3";

export const persister = createAsyncStoragePersister({
  storage: idbStorage,
  key: "cairn-query-cache",
});

/**
 * The single source of truth for how the persisted cache is restored and
 * saved. Both `restoreQueryClient` and `subscribeToPersist` below spread
 * this, so the two halves can never drift apart.
 *
 * `maxAge: Infinity` is load-bearing, not decoration. ADR 0005: "No hard
 * client-side TTL; a `buster` string bumped on breaking API/schema changes
 * is the only thing that invalidates the persisted cache outright."
 * `persistQueryClientRestore` defaults `maxAge` to **24 hours** and, once
 * past it, calls `persister.removeClient()` — it *deletes* the cache
 * rather than merely distrusting it. Away from home that turns spec 6.2's
 * "if it fails, the cache stands" into a blank app roughly one day after
 * the last time it was opened at home, which is exactly the window in
 * which someone would actually want to check their net worth from a train.
 *
 * Staleness is shown, never enforced: the freshness strip reads each
 * query's own `dataUpdatedAt` (see lib/freshness.ts) and tints anything
 * older than 24h, which is spec 6.2's designated mechanism for "never a
 * stale number that looks fresh". Deleting the data is not a substitute
 * for labelling it.
 */
export const persistOptions = {
  persister,
  buster: CACHE_BUSTER,
  maxAge: Infinity,
  dehydrateOptions: {
    // Persist anything that *has* an answer, not only queries whose last
    // fetch succeeded.
    //
    // TanStack's `defaultShouldDehydrateQuery` is
    // `query.state.status === "success"`, and the cache is re-saved on
    // every cache change — including the moment a refetch fails. So one
    // opened-while-away session was enough to erase the offline cache: the
    // cards rendered from IndexedDB, the refetches against the unreachable
    // Pi failed, every one of those queries flipped to `status: "error"`
    // while still holding its data, and the very next save dropped them
    // from IndexedDB for having failed. Open the app away from home twice
    // and the second time it had nothing left to show — the first visit
    // silently consumed the cache it was reading from.
    //
    // `data !== undefined` is the honest test of "is there something worth
    // keeping": a query that failed with a value still in hand is exactly
    // the stale-but-useful case spec 6.2 wants preserved, and one that
    // never resolved has nothing to write down either way.
    shouldDehydrateQuery: (query: { state: { data: unknown } }) =>
      query.state.data !== undefined,
  },
};

// A few seconds is generous for a local IndexedDB open/read on a Pi-served
// LAN app, and short enough that a genuine hang — a `blocked` IDB upgrade
// held open by another tab, or WebKit's "IDB open never resolves after
// suspend/resume" condition on iOS Safari/standalone PWAs — doesn't read as
// a dead app. Only a force-quit recovered from that before this existed.
export const RESTORE_TIMEOUT_MS = 4000;

/**
 * Bounded replacement for what `PersistQueryClientProvider` does
 * internally: it `await`s `persistQueryClientRestore(...)` guarded only by
 * `.catch()`, which handles a *rejected* promise, not one that never
 * settles. If the IndexedDB open genuinely hangs, that leaves `isRestoring`
 * stuck `true` forever — no query ever fetches, and even the refresh button
 * does nothing, since `invalidateQueries()` can't refetch a query with no
 * subscribed observers yet.
 *
 * This races the same restore against a timeout so the app always reaches
 * a live state either way. Losing the cache is strictly better than a
 * permanently dead app. Resolves — never rejects — regardless of which
 * side of the race wins.
 *
 * Caveat: if the restore is merely slow rather than truly hung, it can
 * still resolve after the timeout has already let the app move on; the
 * (now-late) `hydrate()` inside `persistQueryClientRestore` runs anyway and
 * could overwrite an already-live query with older cached data. Accepted —
 * this path only matters for the rare stuck-open case this exists to route
 * around, and a subsequent refetch (manual or on next mount) corrects it.
 */
export function restoreQueryClient(
  queryClient: QueryClient,
  timeoutMs: number = RESTORE_TIMEOUT_MS,
): Promise<void> {
  const restore = persistQueryClientRestore({
    queryClient,
    ...persistOptions,
  }).catch(() => {
    // persistQueryClientRestore already discards the persisted client and
    // rethrows on a genuine failure (corrupt entry, decode error) — nothing
    // left to do here but stop that rejection from winning the race below.
  });
  const timeout = new Promise<void>((resolve) => {
    setTimeout(resolve, timeoutMs);
  });
  return Promise.race([restore, timeout]);
}

/** Starts persisting future cache changes to IndexedDB. Call once restoring
 * has finished (bounded or not) — mirrors what `PersistQueryClientProvider`
 * wires up internally right after its own (unbounded) restore settles. */
export function subscribeToPersist(queryClient: QueryClient): () => void {
  return persistQueryClientSubscribe({
    queryClient,
    ...persistOptions,
  });
}
