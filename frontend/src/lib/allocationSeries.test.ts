import { describe, expect, it } from "vitest";
import type { AllocationTimeseriesPoint } from "./api";
import type { AssetClass } from "./assetClasses";
import {
  findCrossings,
  latestMix,
  linearProjection,
  milestoneLadder,
  sumSelected,
  type SeriesPoint,
} from "./allocationSeries";

const all = (...classes: AssetClass[]) => new Set<AssetClass>(classes);

function point(
  date: string,
  values: Partial<Record<AssetClass, string>>,
): AllocationTimeseriesPoint {
  return { date, values: values as Record<string, string> };
}

/** Monthly series, first of each month, values given in order. */
function monthly(startYear: number, values: number[]): SeriesPoint[] {
  return values.map((value, i) => {
    const month = (i % 12) + 1;
    const year = startYear + Math.floor(i / 12);
    return { date: `${year}-${String(month).padStart(2, "0")}-01`, value };
  });
}

describe("sumSelected", () => {
  const points = [
    point("2024-01-01", { EQUITY: "1000.50", CASH: "500", LIABILITY: "-200" }),
    point("2024-02-01", { EQUITY: "1100", LIABILITY: "-190" }),
  ];

  it("adds only the selected classes", () => {
    expect(sumSelected(points, all("EQUITY"))).toEqual([
      { date: "2024-01-01", value: 1000.5 },
      { date: "2024-02-01", value: 1100 },
    ]);
  });

  it("treats a missing bucket as zero rather than dropping the point", () => {
    // CASH is absent on 2024-02-01; the point must still be emitted.
    expect(sumSelected(points, all("CASH"))).toEqual([
      { date: "2024-01-01", value: 500 },
      { date: "2024-02-01", value: 0 },
    ]);
  });

  it("subtracts LIABILITY, which arrives negative", () => {
    expect(sumSelected(points, all("EQUITY", "LIABILITY"))).toEqual([
      { date: "2024-01-01", value: 800.5 },
      { date: "2024-02-01", value: 910 },
    ]);
  });

  it("returns an empty series for empty input", () => {
    expect(sumSelected([], all("EQUITY"))).toEqual([]);
  });
});

describe("latestMix", () => {
  it("orders by ASSET_CLASSES, not by the selection or the payload", () => {
    const p = point("2024-01-01", {
      CASH: "300",
      EQUITY: "1000",
      LIABILITY: "-50",
    });
    // Selection built in a deliberately different order.
    const mix = latestMix(p, all("CASH", "LIABILITY", "EQUITY"));
    expect(mix.map((m) => m.cls)).toEqual(["EQUITY", "CASH", "LIABILITY"]);
    expect(mix.map((m) => m.value)).toEqual([1000, 300, -50]);
  });

  it("reports unselected classes not at all and missing ones as zero", () => {
    const p = point("2024-01-01", { EQUITY: "1000" });
    expect(latestMix(p, all("EQUITY", "BOND"))).toEqual([
      { cls: "EQUITY", value: 1000 },
      { cls: "BOND", value: 0 },
    ]);
  });

  it("returns an empty mix for a missing point", () => {
    expect(latestMix(undefined, all("EQUITY"))).toEqual([]);
  });
});

describe("milestoneLadder", () => {
  it("starts at 1000 even for zero or negative wealth", () => {
    expect(milestoneLadder(0)).toEqual([1000]);
    expect(milestoneLadder(-5000)).toEqual([1000]);
  });

  it("ends on the first entry strictly greater than the max", () => {
    expect(milestoneLadder(12_000)).toEqual([
      1000, 2000, 5000, 10_000, 20_000,
    ]);
  });

  it("treats an exactly-equal value as not yet exceeded", () => {
    // 1000 is not > 1000, so the ladder must reach for 2000.
    expect(milestoneLadder(1000)).toEqual([1000, 2000]);
  });

  it("follows the 1/2/5 sequence with no 150k or 300k", () => {
    const ladder = milestoneLadder(250_000);
    expect(ladder).toEqual([
      1000, 2000, 5000, 10_000, 20_000, 50_000, 100_000, 200_000, 500_000,
    ]);
    expect(ladder).not.toContain(150_000);
    expect(ladder).not.toContain(300_000);
  });

  it("is strictly ascending across decades", () => {
    const ladder = milestoneLadder(4_000_000);
    for (let i = 1; i < ladder.length; i++) {
      expect(ladder[i]).toBeGreaterThan(ladder[i - 1]);
    }
    expect(ladder[ladder.length - 1]).toBe(5_000_000);
  });

  it("falls back to the 1000 floor for a non-finite max", () => {
    expect(milestoneLadder(Number.NaN)).toEqual([1000]);
  });
});

describe("findCrossings", () => {
  it("reports the first date at or above each milestone", () => {
    const series = monthly(2024, [500, 1500, 2500, 6000]);
    expect(findCrossings(series, [1000, 2000, 5000])).toEqual([
      { milestone: 1000, date: "2024-02-01" },
      { milestone: 2000, date: "2024-03-01" },
      { milestone: 5000, date: "2024-04-01" },
    ]);
  });

  it("counts an exact hit as crossed", () => {
    const series = monthly(2024, [999, 1000]);
    expect(findCrossings(series, [1000])).toEqual([
      { milestone: 1000, date: "2024-02-01" },
    ]);
  });

  it("keeps the FIRST crossing when a milestone is lost and regained", () => {
    // Up through 1000, back below it, then above again.
    const series = monthly(2024, [800, 1200, 700, 1300]);
    expect(findCrossings(series, [1000])).toEqual([
      { milestone: 1000, date: "2024-02-01" },
    ]);
  });

  it("omits milestones never reached", () => {
    const series = monthly(2024, [500, 900]);
    expect(findCrossings(series, [1000, 2000])).toEqual([]);
  });

  it("handles an empty series", () => {
    expect(findCrossings([], [1000])).toEqual([]);
  });
});

describe("linearProjection", () => {
  it("projects a forward date for a rising series", () => {
    // +1000 per month, last observation 13 000 on 2024-04-01.
    const series = monthly(2024, [10_000, 11_000, 12_000, 13_000]);
    const projected = linearProjection(series, 15_000);
    expect(projected).not.toBeNull();
    // Two more months of the same slope lands around June 2024.
    expect(projected! > "2024-04-01").toBe(true);
    expect(projected! < "2024-09-01").toBe(true);
  });

  it("returns null for a flat series", () => {
    expect(linearProjection(monthly(2024, [5000, 5000, 5000]), 10_000)).toBeNull();
  });

  it("returns null for a falling series", () => {
    expect(linearProjection(monthly(2024, [9000, 8000, 7000]), 10_000)).toBeNull();
  });

  it("returns null when the target is already reached", () => {
    expect(linearProjection(monthly(2024, [1000, 5000, 9000]), 9000)).toBeNull();
  });

  it("returns null when the projection is absurdly far out", () => {
    // A near-flat slope would put a million-euro target centuries away.
    const series: SeriesPoint[] = [
      { date: "2024-01-01", value: 1000 },
      { date: "2024-04-01", value: 1000.01 },
    ];
    expect(linearProjection(series, 1_000_000)).toBeNull();
  });

  it("returns null with fewer than two points", () => {
    expect(linearProjection([{ date: "2024-01-01", value: 1 }], 1000)).toBeNull();
    expect(linearProjection([], 1000)).toBeNull();
  });

  it("returns null when every point shares one date", () => {
    const series: SeriesPoint[] = [
      { date: "2024-01-01", value: 1000 },
      { date: "2024-01-01", value: 2000 },
    ];
    expect(linearProjection(series, 5000)).toBeNull();
  });

  it("ignores history older than the trailing fit window", () => {
    // A decade of stagnation followed by a steep final year must project
    // off the recent slope, not the flat prehistory.
    const old: SeriesPoint[] = [
      { date: "2014-01-01", value: 1000 },
      { date: "2019-01-01", value: 1000 },
    ];
    const recent: SeriesPoint[] = [
      { date: "2024-01-01", value: 10_000 },
      { date: "2024-07-01", value: 40_000 },
      { date: "2024-12-01", value: 70_000 },
    ];
    const projected = linearProjection([...old, ...recent], 100_000);
    expect(projected).not.toBeNull();
    expect(projected! < "2025-12-01").toBe(true);
  });

  it("returns null for a non-finite target", () => {
    expect(linearProjection(monthly(2024, [1000, 2000]), Number.NaN)).toBeNull();
  });
});
