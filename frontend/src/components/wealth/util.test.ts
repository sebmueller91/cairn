import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { frameIndices, PERIODS, rangeFor, type Granularity } from "./util";

describe("rangeFor", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-16T12:00:00Z"));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("offers 5Y between 1Y and MAX", () => {
    expect(PERIODS).toEqual(["1M", "3M", "6M", "1Y", "5Y", "MAX"]);
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
