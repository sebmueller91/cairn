import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HERO_DAYS, closestPoint, hoursSince, netWorthQueryKey } from "./utils";

describe("netWorthQueryKey", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  // The regression this file exists for. The key used to end in
  // `isoDaysAgo(0)`, so at local midnight it became a key IndexedDB had
  // never seen: `data` undefined, the fetch to an unreachable Pi failing,
  // and the hero rendering an error over a cache that still held yesterday's
  // number under yesterday's key. See lib/queryState.ts.
  it("does not change across local midnight", () => {
    vi.setSystemTime(new Date(2026, 7, 29, 23, 59, 0));
    const before = netWorthQueryKey();
    vi.setSystemTime(new Date(2026, 7, 30, 0, 1, 0));
    const after = netWorthQueryKey();
    expect(after).toEqual(before);
  });

  it("carries no date-shaped segment at all", () => {
    vi.setSystemTime(new Date(2026, 7, 29, 12, 0, 0));
    for (const part of netWorthQueryKey()) {
      expect(String(part)).not.toMatch(/\d{4}-\d{2}-\d{2}/);
    }
  });

  it("names the window it describes, so a changed window is a new key", () => {
    expect(netWorthQueryKey()).toEqual(["networth", "overview", HERO_DAYS]);
  });
});

describe("closestPoint", () => {
  it("has nothing to return for an empty series", () => {
    expect(closestPoint([], new Date())).toBeNull();
  });

  it("finds the nearest date without needing an exact match", () => {
    // Weekends and holidays mean "30 days ago" often isn't in the series.
    const points = [
      { date: "2026-07-03" },
      { date: "2026-07-31" },
      { date: "2026-08-28" },
    ];
    expect(closestPoint(points, new Date("2026-07-29T00:00:00Z"))).toEqual({
      date: "2026-07-31",
    });
  });
});

describe("hoursSince", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-29T12:00:00Z"));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("is null when the thing never happened", () => {
    expect(hoursSince(null)).toBeNull();
    expect(hoursSince(undefined)).toBeNull();
    expect(hoursSince("not a timestamp")).toBeNull();
  });

  it("counts hours since an ISO timestamp", () => {
    expect(hoursSince("2026-08-29T06:00:00Z")).toBe(6);
  });
});
