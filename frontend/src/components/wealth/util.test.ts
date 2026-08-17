import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PERIODS, rangeFor, type Granularity } from "./util";

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
