import { afterEach, describe, expect, it, vi } from "vitest";
import { QueryClient } from "@tanstack/react-query";

// Stub the underlying restore so it can be made to hang or reject on
// command — the real one talks to IndexedDB via idb-keyval, which isn't
// available in this (Node, non-jsdom) test environment, and the point of
// these tests is the timeout race itself, not idb-keyval.
const persistQueryClientRestore = vi.fn();
vi.mock("@tanstack/react-query-persist-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tanstack/react-query-persist-client")>();
  return {
    ...actual,
    persistQueryClientRestore: (...args: unknown[]) => persistQueryClientRestore(...args),
  };
});

const { RESTORE_TIMEOUT_MS, persistOptions, restoreQueryClient } = await import("./persister");

describe("restoreQueryClient", () => {
  afterEach(() => {
    vi.useRealTimers();
    persistQueryClientRestore.mockReset();
  });

  it("resolves once the timeout elapses even if the restore never settles", async () => {
    vi.useFakeTimers();
    persistQueryClientRestore.mockReturnValue(new Promise(() => {})); // never settles — the iOS hang
    const queryClient = new QueryClient();

    let settled = false;
    restoreQueryClient(queryClient, 50).then(() => {
      settled = true;
    });

    await vi.advanceTimersByTimeAsync(10);
    expect(settled).toBe(false);

    await vi.advanceTimersByTimeAsync(60);
    expect(settled).toBe(true);
  });

  it("resolves (not rejects) when the restore itself rejects", async () => {
    persistQueryClientRestore.mockReturnValue(Promise.reject(new Error("corrupt cache entry")));
    const queryClient = new QueryClient();
    await expect(restoreQueryClient(queryClient, 1000)).resolves.toBeUndefined();
  });

  it("resolves promptly when the restore succeeds well within the timeout", async () => {
    persistQueryClientRestore.mockReturnValue(Promise.resolve());
    const queryClient = new QueryClient();
    await expect(restoreQueryClient(queryClient, 10_000)).resolves.toBeUndefined();
  });

  it("defaults to a multi-second timeout, not an instant one", () => {
    expect(RESTORE_TIMEOUT_MS).toBeGreaterThanOrEqual(2000);
  });
});

describe("persisted cache lifetime", () => {
  afterEach(() => {
    persistQueryClientRestore.mockReset();
  });

  it("never expires the persisted cache on age", () => {
    // ADR 0005: "No hard client-side TTL; a `buster` string bumped on
    // breaking API/schema changes is the only thing that invalidates the
    // persisted cache outright."
    expect(persistOptions.maxAge).toBe(Infinity);
    expect(persistOptions.buster).not.toBe("");
  });

  it("passes maxAge through to the restore, not just declares it", () => {
    // The regression this exists for: persistOptions carried
    // maxAge: Infinity while restoreQueryClient built its own argument
    // object and left maxAge out, so persistQueryClientRestore fell back
    // to its 24-hour default — and past that it calls
    // persister.removeClient(), which *deletes* the cache rather than
    // merely distrusting it. The app went blank away from home roughly a
    // day after it was last opened at home, with the declared intent
    // sitting right there in the file the whole time.
    persistQueryClientRestore.mockReturnValue(Promise.resolve());
    restoreQueryClient(new QueryClient(), 1000);

    const args = persistQueryClientRestore.mock.calls[0][0] as { maxAge?: number };
    expect(args.maxAge).toBe(Infinity);
  });

  it("hands the restore a maxAge that outlives a long trip away from home", () => {
    // Stated as the behaviour rather than the literal, so swapping
    // Infinity for a very long finite TTL stays a passing change and
    // sliding back under a day does not.
    const TWO_WEEKS_MS = 14 * 24 * 60 * 60 * 1000;
    persistQueryClientRestore.mockReturnValue(Promise.resolve());
    restoreQueryClient(new QueryClient(), 1000);

    const args = persistQueryClientRestore.mock.calls[0][0] as { maxAge?: number };
    expect(args.maxAge).toBeGreaterThan(TWO_WEEKS_MS);
  });
});

describe("what gets written back to IndexedDB", () => {
  const dehydrate = (data: unknown, status: string) =>
    persistOptions.dehydrateOptions.shouldDehydrateQuery({
      state: { data, status },
    } as never);

  it("keeps a query that still holds data after its refetch failed", () => {
    // The erosion bug: TanStack's default predicate is
    // `status === "success"`, and the persisted cache is rewritten on
    // every cache change — including the moment a refetch fails. Opening
    // the app away from home rendered the cached numbers and then, a
    // second later, deleted exactly those queries from IndexedDB for
    // having failed. The second trip away from home had nothing left.
    expect(dehydrate([{ value_eur: "1.00" }], "error")).toBe(true);
  });

  it("keeps a successful query, as before", () => {
    expect(dehydrate([{ value_eur: "1.00" }], "success")).toBe(true);
  });

  it("does not write down a query that never resolved", () => {
    // Nothing to keep, whether it is still in flight or failed outright.
    expect(dehydrate(undefined, "pending")).toBe(false);
    expect(dehydrate(undefined, "error")).toBe(false);
  });
});
