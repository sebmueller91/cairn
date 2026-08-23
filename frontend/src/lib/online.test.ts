import { describe, expect, it, vi } from "vitest";
import { checkReachable } from "./online";

describe("checkReachable", () => {
  it("is true when the API responds ok", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response(null, { status: 200 }));
    await expect(checkReachable(fetchImpl, "/api/health")).resolves.toBe(true);
  });

  it("is false when the API responds with an error status", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response(null, { status: 503 }));
    await expect(checkReachable(fetchImpl, "/api/health")).resolves.toBe(false);
  });

  it("is false when the request rejects (DNS/connection failure)", async () => {
    const fetchImpl = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(checkReachable(fetchImpl, "/api/health")).resolves.toBe(false);
  });

  it("is false when the request never settles within the timeout", async () => {
    vi.useFakeTimers();
    const fetchImpl = vi.fn((_path: string, init?: RequestInit) => {
      return new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
      });
    });
    const result = checkReachable(fetchImpl as unknown as typeof fetch, "/api/health", 50);
    await vi.advanceTimersByTimeAsync(60);
    await expect(result).resolves.toBe(false);
    vi.useRealTimers();
  });

  it("defaults to the health endpoint", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response(null, { status: 200 }));
    await checkReachable(fetchImpl);
    expect(fetchImpl).toHaveBeenCalledWith(
      "/api/health",
      expect.objectContaining({ method: "GET", cache: "no-store" }),
    );
  });
});
