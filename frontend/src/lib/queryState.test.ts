import { describe, expect, it } from "vitest";
import {
  DEFAULT_STALE_MS,
  cacheStands,
  computeIsQueryLoading,
  msUntilNextLocalDay,
  staleTimeWithinLocalDay,
} from "./queryState";

describe("computeIsQueryLoading", () => {
  it("is loading while the persister restore is in flight, regardless of isPending", () => {
    // This is the exact case query.isLoading gets wrong: fetchStatus is
    // forced idle during restore, so isPending && isFetching is false even
    // though nothing has been decided yet.
    expect(computeIsQueryLoading(true, false)).toBe(true);
    expect(computeIsQueryLoading(true, true)).toBe(true);
  });

  it("defers to isPending once restoring has finished", () => {
    expect(computeIsQueryLoading(false, true)).toBe(true);
    expect(computeIsQueryLoading(false, false)).toBe(false);
  });
});

describe("cacheStands", () => {
  it("holds a failed refetch back when there is cached data to keep showing", () => {
    // Spec 6.2: "if it fails (away from home), the cache stands." The
    // phone is on cellular, so navigator.onLine is true and the fetch to
    // the Pi genuinely runs and genuinely fails — but IndexedDB already
    // handed us the last known numbers, and those are what the user came
    // to see.
    expect(cacheStands(true, [{ date: "2026-08-01", value_eur: "1.00" }])).toBe(true);
  });

  it("still reports an error when the failure left nothing to fall back on", () => {
    // A card that sat on a skeleton forever would be worse than saying so.
    expect(cacheStands(true, undefined)).toBe(false);
  });

  it("does not touch a query that succeeded", () => {
    expect(cacheStands(false, [])).toBe(false);
    expect(cacheStands(false, undefined)).toBe(false);
  });

  it("treats an empty but present answer as data worth keeping", () => {
    // `[]` and `null` are real server answers ("no positions", "no
    // milestone yet"), not absence — only `undefined` means "never
    // arrived". Falling through to the error branch here would replace a
    // legitimately empty view with a failure message.
    expect(cacheStands(true, [])).toBe(true);
    expect(cacheStands(true, null)).toBe(true);
    expect(cacheStands(true, 0)).toBe(true);
  });
});

describe("msUntilNextLocalDay", () => {
  it("measures to the next local midnight, not to UTC midnight", () => {
    // 12:00 UTC on a CEST day is 14:00 local, so ten hours remain locally
    // — a UTC-based answer would say twelve.
    const noonUtc = new Date("2026-08-29T12:00:00Z").getTime();
    expect(msUntilNextLocalDay(noonUtc)).toBe(10 * 3_600_000);
  });

  it("returns a full day at exactly local midnight", () => {
    const localMidnight = new Date(2026, 7, 29, 0, 0, 0, 0).getTime();
    expect(msUntilNextLocalDay(localMidnight)).toBe(24 * 3_600_000);
  });

  it("is 23 hours on the spring-forward day", () => {
    // Europe/Berlin, 29 March 2026. Adding 86_400_000 ms would overshoot
    // midnight by an hour and call yesterday's window fresh into the
    // afternoon of the new day.
    const springForward = new Date(2026, 2, 29, 0, 0, 0, 0).getTime();
    expect(msUntilNextLocalDay(springForward)).toBe(23 * 3_600_000);
  });

  it("is 25 hours on the fall-back day", () => {
    const fallBack = new Date(2026, 9, 25, 0, 0, 0, 0).getTime();
    expect(msUntilNextLocalDay(fallBack)).toBe(25 * 3_600_000);
  });
});

describe("staleTimeWithinLocalDay", () => {
  it("is the plain default for most of the day", () => {
    const midday = new Date(2026, 7, 29, 12, 0, 0, 0).getTime();
    expect(staleTimeWithinLocalDay(midday)).toBe(DEFAULT_STALE_MS);
  });

  it("never reaches past local midnight", () => {
    // Ten seconds before midnight, the answer describes a window that is
    // about to be the wrong one — it may stay fresh for ten seconds, not
    // thirty. This is what replaced putting today's date in the query key.
    const almostMidnight = new Date(2026, 7, 29, 23, 59, 50, 0).getTime();
    expect(staleTimeWithinLocalDay(almostMidnight)).toBe(10_000);
  });

  it("is zero exactly at midnight", () => {
    const midnight = new Date(2026, 7, 30, 0, 0, 0, 0).getTime();
    // A hair before the boundary is already spent; at the boundary the
    // previous day's answer is stale outright.
    expect(staleTimeWithinLocalDay(midnight - 1)).toBe(1);
  });

  it("treats never-fetched as stale", () => {
    expect(staleTimeWithinLocalDay(0)).toBe(0);
  });
});
