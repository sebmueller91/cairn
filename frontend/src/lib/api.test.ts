import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, authEvents, responseTimestamps, shouldRetry, UNAUTHORIZED_EVENT } from "./api";

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

function textResponse(status: number, body: string) {
  return new Response(body, { status, headers: { "Content-Type": "text/plain" } });
}

describe("request() error parsing", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("reads the backend's own {code, params} shape", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(409, { detail: { code: "sell_exceeds_holding", params: { max: "3" } } }),
      ),
    );
    await expect(api.get("/api/x")).rejects.toMatchObject({
      code: "sell_exceeds_holding",
      params: { max: "3" },
      status: 409,
    });
  });

  it("maps FastAPI's list-shaped validation detail to a translatable code", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(422, {
          detail: [{ loc: ["body", "quantity"], msg: "field required", type: "missing" }],
        }),
      ),
    );
    let caught: unknown;
    try {
      await api.get("/api/x");
    } catch (err) {
      caught = err;
    }
    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).code).toBe("validation_error");
    expect((caught as ApiError).params).toEqual({ field: "quantity" });
    expect((caught as ApiError).status).toBe(422);
  });

  it("falls back to a generic code for a non-JSON error body", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(textResponse(500, "Internal Server Error")));
    await expect(api.get("/api/x")).rejects.toMatchObject({ code: "generic", status: 500 });
  });

  it("dispatches the unauthorized event on a 401", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(401, { detail: { code: "unauthorized", params: {} } })),
    );
    const handler = vi.fn();
    authEvents.addEventListener(UNAUTHORIZED_EVENT, handler);
    await expect(api.get("/api/x")).rejects.toBeInstanceOf(ApiError);
    authEvents.removeEventListener(UNAUTHORIZED_EVENT, handler);
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("does not dispatch the unauthorized event on other errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(404, { detail: { code: "account_not_found", params: {} } })),
    );
    const handler = vi.fn();
    authEvents.addEventListener(UNAUTHORIZED_EVENT, handler);
    await expect(api.get("/api/x")).rejects.toBeInstanceOf(ApiError);
    authEvents.removeEventListener(UNAUTHORIZED_EVENT, handler);
    expect(handler).not.toHaveBeenCalled();
  });

  it("records the response's Date header against the parsed body", async () => {
    const when = "Wed, 12 Aug 2026 22:31:00 GMT";
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(200, { value_eur: "100" }, { Date: when })),
    );
    const data = await api.get<{ value_eur: string }>("/api/x");
    expect(responseTimestamps.get(data)).toBe(Date.parse(when));
  });
});

describe("shouldRetry", () => {
  it("never retries a 4xx", () => {
    expect(shouldRetry(0, new ApiError(401, "unauthorized", {}))).toBe(false);
    expect(shouldRetry(0, new ApiError(404, "account_not_found", {}))).toBe(false);
    expect(shouldRetry(0, new ApiError(422, "validation_error", {}))).toBe(false);
  });

  it("retries a transient 5xx once", () => {
    expect(shouldRetry(0, new ApiError(503, "generic", {}))).toBe(true);
    expect(shouldRetry(1, new ApiError(503, "generic", {}))).toBe(false);
  });

  it("retries a non-ApiError (network failure) once", () => {
    expect(shouldRetry(0, new TypeError("Failed to fetch"))).toBe(true);
    expect(shouldRetry(1, new TypeError("Failed to fetch"))).toBe(false);
  });
});
