import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { isoDaysAgo, isoMonthsAgo, localISODate } from "./localDate";

// These helpers exist because `toISOString()` is wrong here. The suite runs
// under TZ=Europe/Berlin (pinned in package.json's test script) so "local"
// is a positive UTC offset — the case that actually breaks. On a UTC runner
// the question these tests ask cannot even be posed.
describe("localISODate", () => {
  it("reads the local calendar fields, not the UTC ones", () => {
    // 00:30 CEST on the 30th is 22:30 UTC on the 29th. `toISOString()`
    // would say the 29th; the local day is the 30th.
    const d = new Date("2026-08-29T22:30:00Z");
    expect(d.toISOString().slice(0, 10)).toBe("2026-08-29");
    expect(localISODate(d)).toBe("2026-08-30");
  });

  it("zero-pads single-digit months and days", () => {
    expect(localISODate(new Date(2026, 0, 5, 12))).toBe("2026-01-05");
  });
});

describe("isoDaysAgo", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns today for 0", () => {
    vi.setSystemTime(new Date("2026-08-29T12:00:00Z"));
    expect(isoDaysAgo(0)).toBe("2026-08-29");
  });

  it("still returns today in the early hours of the local day", () => {
    // The whole reason this helper is hand-rolled: at 00:30 local the UTC
    // date is still yesterday, and asking the API for yesterday's window
    // would quietly drop a day off every rolling range.
    vi.setSystemTime(new Date("2026-08-29T22:30:00Z")); // 00:30 local, 30 Aug
    expect(isoDaysAgo(0)).toBe("2026-08-30");
  });

  it("steps back across a month boundary", () => {
    vi.setSystemTime(new Date("2026-03-05T12:00:00Z"));
    expect(isoDaysAgo(14)).toBe("2026-02-19");
  });

  it("steps back across a year boundary", () => {
    vi.setSystemTime(new Date("2026-01-03T12:00:00Z"));
    expect(isoDaysAgo(7)).toBe("2025-12-27");
  });

  it("crosses a DST transition without losing or gaining a day", () => {
    // Europe/Berlin springs forward on 29 March 2026. Counting back seven
    // calendar days from 31 March must land on 24 March, not 23:00 on the
    // 23rd — which is what subtracting 7 * 86_400_000 ms would give.
    vi.setSystemTime(new Date("2026-03-31T10:00:00Z"));
    expect(isoDaysAgo(7)).toBe("2026-03-24");
  });
});

describe("isoMonthsAgo", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("steps back whole months", () => {
    vi.setSystemTime(new Date("2026-08-16T12:00:00Z"));
    expect(isoMonthsAgo(1)).toBe("2026-07-16");
    expect(isoMonthsAgo(12)).toBe("2025-08-16");
    expect(isoMonthsAgo(60)).toBe("2021-08-16");
  });

  it("reads the local day, not the UTC one", () => {
    vi.setSystemTime(new Date("2026-08-31T22:30:00Z")); // 00:30 local, 1 Sep
    expect(isoMonthsAgo(1)).toBe("2026-08-01");
  });
});
