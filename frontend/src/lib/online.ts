import { useCallback, useEffect, useRef, useState } from "react";

// Offline writes are deliberately not supported (spec 6.2, ADR 0005) — a
// sync queue with conflict resolution needed once a year isn't worth the
// complexity for an agent-driven app that writes at home anyway. This is
// the one place that decision gets enforced; every form just disables
// itself based on this.
//
// ADR 0005: "backed by an actual reachability check, not just the browser
// flag". The bare `navigator.onLine` flag is close to useless for a
// LAN-only app: it reads `true` on cellular data away from home with the
// Pi completely unreachable (worst case: mutating forms stay enabled and
// silently fail against a server that was never reachable), and an iOS
// Wi-Fi<->cellular handoff can fire a spurious `offline` event against an
// app that's actually working fine. So the flag is used only as a *fast
// negative*: `navigator.onLine === false` short-circuits straight to
// "offline" (there's definitely no network to reach anything on), and
// every other reading is verified with a real request to the API before
// being trusted.
const PROBE_PATH = "/api/health";
const PROBE_TIMEOUT_MS = 3_000;
// Re-probes on this cadence whenever the browser flag claims "online", so a
// server that quietly became unreachable is caught even without an
// online/offline browser event ever firing.
const PROBE_INTERVAL_MS = 30_000;

/**
 * One reachability check against the API. Exported (in addition to the
 * hook below) so it has its own unit test independent of React — inject a
 * `fetchImpl` to avoid depending on jsdom/a real network in tests.
 *
 * Caveat this can't fix from here: `/api/health` goes through the service
 * worker's `NetworkFirst` route for `/api/*` (vite.config.ts, not owned by
 * this file). If a prior successful health check is still sitting in that
 * cache, a currently-unreachable API can still resolve from it and read as
 * reachable — e.g. leaving home on cellular minutes after a working LAN
 * session. A fully precise signal needs that route to exempt this probe
 * (e.g. `NetworkOnly`), which is outside this file's ownership.
 */
export async function checkReachable(
  fetchImpl: typeof fetch = fetch,
  path: string = PROBE_PATH,
  timeoutMs: number = PROBE_TIMEOUT_MS,
): Promise<boolean> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetchImpl(path, {
      method: "GET",
      cache: "no-store",
      credentials: "include",
      signal: controller.signal,
    });
    return res.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timeout);
  }
}

export function useOnlineStatus(): boolean {
  const [online, setOnline] = useState(navigator.onLine);
  const inFlight = useRef(false);

  const probe = useCallback(async () => {
    if (!navigator.onLine) {
      // Fast negative — no point spending a round trip to confirm what the
      // browser already knows for certain.
      setOnline(false);
      return;
    }
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      setOnline(await checkReachable());
    } finally {
      inFlight.current = false;
    }
  }, []);

  useEffect(() => {
    probe();
    window.addEventListener("online", probe);
    window.addEventListener("offline", probe);
    const interval = setInterval(probe, PROBE_INTERVAL_MS);
    return () => {
      window.removeEventListener("online", probe);
      window.removeEventListener("offline", probe);
      clearInterval(interval);
    };
  }, [probe]);

  return online;
}
