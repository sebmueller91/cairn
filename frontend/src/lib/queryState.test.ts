import { describe, expect, it } from "vitest";
import { cacheStands, computeIsQueryLoading } from "./queryState";

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

describe("cacheStands", () => {
  it("holds a failed refetch back when there is cached data to keep showing", () => {
    // Spec 6.2: "if it fails (away from home), the cache stands." The
    // phone is on cellular, so navigator.onLine is true and the fetch to
    // the Pi genuinely runs and genuinely fails — but IndexedDB already
    // handed us the last known numbers, and those are what the user came
    // to see.
    expect(cacheStands(true, [{ date: "2026-08-01", value_eur: "1.00" }])).toBe(true);
  });

  it("still reports an error when the failure left nothing to fall back on", () => {
    // A card that sat on a skeleton forever would be worse than saying so.
    expect(cacheStands(true, undefined)).toBe(false);
  });

  it("does not touch a query that succeeded", () => {
    expect(cacheStands(false, [])).toBe(false);
    expect(cacheStands(false, undefined)).toBe(false);
  });

  it("treats an empty but present answer as data worth keeping", () => {
    // `[]` and `null` are real server answers ("no positions", "no
    // milestone yet"), not absence — only `undefined` means "never
    // arrived". Falling through to the error branch here would replace a
    // legitimately empty view with a failure message.
    expect(cacheStands(true, [])).toBe(true);
    expect(cacheStands(true, null)).toBe(true);
    expect(cacheStands(true, 0)).toBe(true);
  });
});
