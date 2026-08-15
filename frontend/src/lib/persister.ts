import { get, set, del } from "idb-keyval";
import { createAsyncStoragePersister } from "@tanstack/query-async-storage-persister";

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
const CACHE_BUSTER = "1";

export const persister = createAsyncStoragePersister({
  storage: idbStorage,
  key: "cairn-query-cache",
});

export const persistOptions = {
  persister,
  buster: CACHE_BUSTER,
  maxAge: Infinity as number, // no expiry — staleness is shown, not enforced (spec 6.2)
};
