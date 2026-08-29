import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  frameIndices,
  granularityFor,
  PERIODS,
  rangeFor,
  type Granularity,
} from "./util";

describe("rangeFor", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-16T12:00:00Z"));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("offers the full ladder from a week to everything", () => {
    expect(PERIODS).toEqual(["7D", "1M", "3M", "6M", "1Y", "5Y", "MAX"]);
  });

  it("looks back seven days for 7D, at daily resolution", () => {
    expect(rangeFor("7D")).toEqual({ from: "2026-08-09", granularity: "day" });
  });

  it("looks back five years for 5Y", () => {
    expect(rangeFor("5Y").from).toBe("2021-08-16");
  });

  it("keeps 5Y weekly so drawdowns stay visible", () => {
    expect(rangeFor("5Y").granularity).toBe("week");
  });

  it("only MAX is unbounded", () => {
    for (const period of PERIODS) {
      const hasLowerBound = rangeFor(period).from !== undefined;
      expect(hasLowerBound).toBe(period !== "MAX");
    }
  });

  it("never gets finer as the range widens", () => {
    // The whole point of the ladder (ADR 0004): a wider window must not
    // ask the API for denser buckets than a narrower one.
    const rank: Record<Granularity, number> = { day: 0, week: 1, month: 2 };
    const grains = PERIODS.map((p) => rank[rangeFor(p).granularity]);
    const sorted = [...grains].sort((a, b) => a - b);
    expect(grains).toEqual(sorted);
  });

  it("returns lower bounds in ascending age", () => {
    const bounds = PERIODS.filter((p) => p !== "MAX").map((p) => rangeFor(p).from!);
    expect(bounds).toEqual([...bounds].sort().reverse());
  });
});

describe("frameIndices", () => {
  it("never indexes past the end when the series shrank under the playhead", () => {
    // The regression: playhead at frame 98 from MAX, then a cached 1M range
    // arrives with 30 points and renders before the clamping effect runs.
    // `snap` used to be an unclamped Math.round(frame) and read undefined.
    const { lower, upper, snap } = frameIndices(98, 30);
    expect(lower).toBe(29);
    expect(upper).toBe(29);
    expect(snap).toBe(29);
  });

  it("interpolates between neighbouring buckets", () => {
    const { lower, upper, t01 } = frameIndices(4.25, 10);
    expect(lower).toBe(4);
    expect(upper).toBe(5);
    expect(t01).toBeCloseTo(0.25, 6);
  });

  it("snaps the label to the nearer bucket", () => {
    expect(frameIndices(4.6, 10).snap).toBe(5);
    expect(frameIndices(4.4, 10).snap).toBe(4);
  });

  it("holds the last bucket at the very end", () => {
    const { lower, upper, t01 } = frameIndices(9, 10);
    expect(lower).toBe(9);
    expect(upper).toBe(9);
    expect(t01).toBe(0);
  });

  it("clamps a negative playhead to the start", () => {
    expect(frameIndices(-3, 10)).toEqual({ lower: 0, upper: 1, t01: 0, snap: 0 });
  });

  it("returns zeros for an empty series", () => {
    // Callers still have to check `total > 0` — there is no element 0 to read.
    expect(frameIndices(5, 0)).toEqual({ lower: 0, upper: 0, t01: 0, snap: 0 });
  });

  it("handles a single-point series", () => {
    expect(frameIndices(7, 1)).toEqual({ lower: 0, upper: 0, t01: 0, snap: 0 });
  });
});

describe("the Wealth window query key", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  // Mirrors what pages/Wealth.tsx builds. The `from` bound is deliberately
  // not in it: this page's key used to carry it, so at midnight the curve
  // asked IndexedDB for an entry that had never existed and errored away
  // from home instead of showing the last window it had. See
  // lib/queryState.ts for the rule.
  const keyFor = (period: (typeof PERIODS)[number]) =>
    [
      "allocationTimeseries",
      period === "MAX" ? "all" : period,
      granularityFor(period),
    ] as const;

  it("does not change across local midnight, for any period", () => {
    vi.setSystemTime(new Date(2026, 7, 29, 23, 59, 0));
    const before = PERIODS.map(keyFor);
    vi.setSystemTime(new Date(2026, 7, 30, 0, 1, 0));
    expect(PERIODS.map(keyFor)).toEqual(before);
  });

  it("carries no date-shaped segment at all", () => {
    vi.setSystemTime(new Date(2026, 7, 29, 12, 0, 0));
    for (const period of PERIODS) {
      for (const part of keyFor(period)) {
        expect(String(part)).not.toMatch(/\d{4}-\d{2}-\d{2}/);
      }
    }
  });

  it("still lets MAX share one request with the full-history query", () => {
    // pages/Wealth.tsx mounts a second query on
    // ["allocationTimeseries", "all", "month"] for the milestone journey;
    // at MAX the two must remain literally the same key.
    expect(keyFor("MAX")).toEqual(["allocationTimeseries", "all", "month"]);
  });

  it("gives every other period its own key", () => {
    const keys = PERIODS.map((p) => JSON.stringify(keyFor(p)));
    expect(new Set(keys).size).toBe(PERIODS.length);
  });
});

describe("rangeFor bounds the window on the local day", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("uses the local date, not the UTC one, late in the evening", () => {
    // 23:30 UTC is already 01:30 the next local day in CEST. This page used
    // to build its bounds with `toISOString()`, so its window rolled over
    // an hour or two before the Overview cards' did — the two pages
    // disagreed about what "today" meant for that window.
    vi.setSystemTime(new Date("2026-08-16T23:30:00Z"));
    expect(rangeFor("7D").from).toBe("2026-08-10");
  });

  it("agrees with granularityFor", () => {
    vi.setSystemTime(new Date("2026-08-16T12:00:00Z"));
    for (const period of PERIODS) {
      expect(rangeFor(period).granularity).toBe(granularityFor(period));
    }
  });
});
