import { describe, expect, it } from "vitest";
import { valueAxis } from "./chartTheme";

describe("valueAxis", () => {
  it("frames the data instead of starting at zero", () => {
    // The case that motivated this: half a year of net worth, where a
    // zero-based axis spends 94% of its height on empty space.
    const { domain } = valueAxis([716103.5, 730000, 761962.19]);
    expect(domain[1]).toBeGreaterThan(761962.19);
    // The 46k move fills most of the plot instead of 6% of it.
    expect((761962.19 - 716103.5) / (domain[1] - domain[0])).toBeGreaterThan(0.6);
  });

  it("keeps the whole series inside the frame", () => {
    const values = [12, 47, 33, 8, 51];
    const { domain } = valueAxis(values);
    expect(domain[0]).toBeLessThanOrEqual(Math.min(...values));
    expect(domain[1]).toBeGreaterThanOrEqual(Math.max(...values));
  });

  it("lands ticks on round numbers", () => {
    const { ticks } = valueAxis([716103.5, 761962.19]);
    for (const tick of ticks) expect(tick % 10000).toBe(0);
    expect(ticks.length).toBeGreaterThanOrEqual(3);
    expect(ticks.length).toBeLessThanOrEqual(7);
  });

  it("starts and ends on a tick", () => {
    const { domain, ticks } = valueAxis([716103.5, 730000, 761962.19]);
    expect(ticks[0]).toBe(domain[0]);
    expect(ticks[ticks.length - 1]).toBe(domain[1]);
  });

  it("does not invent negative space under a positive series", () => {
    // Padding a series that sits just above zero must not push the floor
    // below it — an axis reaching -200 under a 100 low reads as debt.
    expect(valueAxis([100, 140]).domain[0]).toBeGreaterThanOrEqual(0);
  });

  it("keeps zero in frame when the series goes negative", () => {
    // Truncation may hide anything except the waterline: "am I under" is
    // the question a scaled axis still has to answer.
    const { domain } = valueAxis([-5000, -3000, -1000]);
    expect(domain[0]).toBeLessThan(0);
    expect(domain[1]).toBeGreaterThanOrEqual(0);
  });

  it("draws a flat series down the middle", () => {
    const { domain } = valueAxis([500, 500, 500]);
    expect(domain[0]).toBeLessThan(500);
    expect(domain[1]).toBeGreaterThan(500);
  });

  it("survives a flat series at zero", () => {
    const { domain } = valueAxis([0, 0]);
    expect(domain[0]).toBeLessThanOrEqual(0);
    expect(domain[1]).toBeGreaterThan(0);
  });

  it("survives an empty series", () => {
    expect(() => valueAxis([])).not.toThrow();
  });
});
