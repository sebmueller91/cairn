import { describe, expect, it } from "vitest";
import { computeIsQueryLoading } from "./queryState";

describe("computeIsQueryLoading", () => {
  it("is loading while the persister restore is in flight, regardless of isPending", () => {
    // This is the exact case query.isLoading gets wrong: fetchStatus is
    // forced idle during restore, so isPending && isFetching is false even
    // though nothing has been decided yet.
    expect(computeIsQueryLoading(true, false)).toBe(true);
    expect(computeIsQueryLoading(true, true)).toBe(true);
  });

  it("defers to isPending once restoring has finished", () => {
    expect(computeIsQueryLoading(false, true)).toBe(true);
    expect(computeIsQueryLoading(false, false)).toBe(false);
  });
});
