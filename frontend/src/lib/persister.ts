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

// Bump this when a schema/API change means old cached shapes would be
// wrong to render — e.g. a renamed field a cached response still has the
// old name for. Not tied to app version generally; only breaking changes
// need it (ADR 0005).
const CACHE_BUSTER = "2";

export const persister = createAsyncStoragePersister({
  storage: idbStorage,
  key: "cairn-query-cache",
});

export const persistOptions = {
  persister,
  buster: CACHE_BUSTER,
  maxAge: Infinity as number, // no expiry — staleness is shown, not enforced (spec 6.2)
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
    persister,
    buster: CACHE_BUSTER,
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
    persister,
    buster: CACHE_BUSTER,
  });
}
