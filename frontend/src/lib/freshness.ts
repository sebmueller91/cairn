import { responseTimestamps } from "./api";

/**
 * The honest "as of" moment for one query's current data.
 *
 * `dataUpdatedAt` is TanStack's own timestamp, stamped when the fetch
 * *promise resolves* — which is indistinguishable from "just fetched" even
 * when the service worker's `NetworkFirst` route (vite.config.ts) served a
 * week-old cached response instead of a live one, since resolving from the
 * Cache API happens just as "now" as resolving from the network. That's
 * exactly the failure mode ADR 0005 rules out ("never show a stale number
 * that looks fresh").
 *
 * `responseTimestamps` (lib/api.ts) reads the HTTP `Date` header instead,
 * which a Cache-API-stored `Response` keeps as originally sent — so it
 * still names the moment the server actually generated that body. Falls
 * back to `dataUpdatedAt` for data that never passed through `request()`
 * (written via `setQueryData`, or hydrated from the IndexedDB persister on
 * a cold start) — accurate in both of those cases already, and there is no
 * `Date` header to read for either.
 */
export function effectiveAsOf(data: unknown, dataUpdatedAt: number): number {
  if (data !== null && typeof data === "object") {
    const serverTime = responseTimestamps.get(data as object);
    if (serverTime != null) return serverTime;
  }
  return dataUpdatedAt;
}
