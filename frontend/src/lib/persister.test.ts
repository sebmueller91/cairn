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

const { RESTORE_TIMEOUT_MS, restoreQueryClient } = await import("./persister");

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
