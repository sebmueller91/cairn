import { describe, expect, it } from "vitest";
import { formatPercent } from "./format";

describe("formatPercent", () => {
  it("defaults to one decimal", () => {
    expect(formatPercent(0.1234, "de")).toContain("12,3");
  });

  // Regression: the tax view asks for whole percent, which used to collide
  // with the hardcoded one-decimal minimum and throw a RangeError, blanking
  // the entire tab rather than just misformatting one number.
  it("accepts maximumFractionDigits: 0 without throwing", () => {
    expect(() => formatPercent(0.5, "de", { maximumFractionDigits: 0 })).not.toThrow();
    expect(formatPercent(0.5, "de", { maximumFractionDigits: 0 })).toContain("50");
  });

  it("raises the maximum when a caller asks for more decimals", () => {
    expect(formatPercent(0.123456, "en", { minimumFractionDigits: 3 })).toContain("12.346");
  });
});
