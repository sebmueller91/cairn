import { describe, expect, it } from "vitest";
import { parseDecimalInput } from "./decimalInput";

describe("parseDecimalInput", () => {
  it("accepts a plain decimal", () => {
    expect(parseDecimalInput("1234.56")).toBe("1234.56");
  });

  it("treats a lone comma as the decimal separator", () => {
    expect(parseDecimalInput("12345,67")).toBe("12345.67");
  });

  it("handles German grouping", () => {
    expect(parseDecimalInput("12.345,67")).toBe("12345.67");
  });

  it("handles English grouping", () => {
    expect(parseDecimalInput("12,345.67")).toBe("12345.67");
  });

  it("ignores a pasted currency symbol and spaces", () => {
    expect(parseDecimalInput("12 345,67 €")).toBe("12345.67");
  });

  it("keeps a lone dot as a decimal point rather than guessing", () => {
    expect(parseDecimalInput("12.345")).toBe("12.345");
  });

  it("keeps negatives", () => {
    expect(parseDecimalInput("-500,25")).toBe("-500.25");
  });

  it("rejects anything that isn't a number", () => {
    expect(parseDecimalInput("")).toBeNull();
    expect(parseDecimalInput("abc")).toBeNull();
    expect(parseDecimalInput("1.2.3,4,5")).toBeNull();
  });
});
