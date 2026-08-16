// Small helpers shared by the Overview cards. Kept local to this directory
// (rather than lib/) since Overview is the only page that owns this shape
// of query — see the ownership note at the top of Overview.tsx.

import { api, type NetWorthPoint } from "../../lib/api";

/** ISO `YYYY-MM-DD` for `days` ago, in local time — matches the `from`
 * query params the timeseries/attribution endpoints expect. */
export function isoDaysAgo(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

/** The point in `points` whose `date` is nearest to `target` — used to find
 * "~30 days ago" in a daily series without assuming an exact match exists
 * (weekends, holidays, or a series that doesn't start early enough). */
export function closestPoint<T extends { date: string }>(
  points: T[],
  target: Date,
): T | null {
  if (points.length === 0) return null;
  let best = points[0];
  let bestDiff = Math.abs(new Date(points[0].date).getTime() - target.getTime());
  for (const p of points) {
    const diff = Math.abs(new Date(p.date).getTime() - target.getTime());
    if (diff < bestDiff) {
      best = p;
      bestDiff = diff;
    }
  }
  return best;
}

/** Hours elapsed since an ISO timestamp, or `null` when there isn't one
 * (never fetched / never snapshotted / never backed up yet). */
export function hoursSince(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return null;
  return (Date.now() - then) / 3_600_000;
}

/** Past this age, a freshness dot flips from green to amber. */
export const STALE_THRESHOLD_HOURS = 48;

/** Net worth (scope=net, so loans count against it), last 90 days at day
 * granularity. Shared between NetWorthHero (the sparkline + delta) and
 * Overview (the page-level "no snapshots yet" check) under the same query
 * key, so it's genuinely one network round trip, not two. */
export function fetchNetWorth90d(): Promise<NetWorthPoint[]> {
  const params = new URLSearchParams({
    scope: "net",
    granularity: "day",
    from: isoDaysAgo(90),
  });
  return api.get<NetWorthPoint[]>(`/api/timeseries/networth?${params}`);
}

export const NET_WORTH_QUERY_KEY = ["networth", "overview"] as const;
