import { describe, expect, it } from "vitest";
import { effectiveAsOf } from "./freshness";
import { responseTimestamps } from "./api";

describe("effectiveAsOf", () => {
  it("prefers the response's Date-header timestamp over dataUpdatedAt", () => {
    // This is the case a service-worker cache fallback breaks: `data`
    // resolved "now" (dataUpdatedAt), but the body itself is a week old.
    const data = { value_eur: "100" };
    const serverTime = Date.parse("2026-08-01T00:00:00Z");
    responseTimestamps.set(data, serverTime);
    const dataUpdatedAt = Date.parse("2026-08-23T12:00:00Z"); // "just now"
    expect(effectiveAsOf(data, dataUpdatedAt)).toBe(serverTime);
  });

  it("falls back to dataUpdatedAt when the data never passed through request()", () => {
    // e.g. written via setQueryData, or hydrated fresh from IndexedDB —
    // dataUpdatedAt is the accurate signal in both of those cases.
    const data = { value_eur: "100" };
    const dataUpdatedAt = Date.parse("2026-08-23T12:00:00Z");
    expect(effectiveAsOf(data, dataUpdatedAt)).toBe(dataUpdatedAt);
  });

  it("falls back to dataUpdatedAt for non-object data", () => {
    expect(effectiveAsOf(undefined, 123)).toBe(123);
    expect(effectiveAsOf(null, 456)).toBe(456);
  });
});
