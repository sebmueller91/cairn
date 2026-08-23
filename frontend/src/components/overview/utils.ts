// Small helpers shared by the Overview cards. Kept local to this directory
// (rather than lib/) since Overview is the only page that owns this shape
// of query — see the ownership note at the top of Overview.tsx.

import { api, type NetWorthPoint } from "../../lib/api";

/** `YYYY-MM-DD` for a `Date`, read from its *local* fields. `toISOString()`
 * converts to UTC first, which silently steps back a day for anyone in a
 * positive UTC offset (all of Central Europe) during the early hours of
 * the local day — before ~01:00 CET / ~02:00 CEST, "today" would come out
 * as yesterday. */
function localISODate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/** ISO `YYYY-MM-DD` for `days` ago, in local time — matches the `from`
 * query params the timeseries/attribution endpoints expect. */
export function isoDaysAgo(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return localISODate(d);
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

/** The offsite (NAS) leg is judged more leniently, mirroring
 * `STALE_OFFSITE_BACKUP_HOURS` in the backend's data_quality_service — a
 * NAS that was rebooting or asleep for a night shouldn't cry wolf. Kept
 * equal to the backend's threshold on purpose: if the dot and the issue
 * list disagreed, the strip would show a green dot next to a warning
 * about the same thing. */
export const STALE_OFFSITE_THRESHOLD_HOURS = 72;

/** The window the Overview hero reports on — both its sparkline and its
 * delta chip. Half a year rather than a month or a quarter: the Overview is
 * meant to answer "where is this heading", and over 30 days a portfolio
 * this size is mostly market noise. One constant so the two figures in the
 * hero can never describe different periods. */
export const HERO_DAYS = 180;

/** Net worth (scope=net, so loans count against it) over HERO_DAYS at day
 * granularity. Shared between NetWorthHero (the sparkline + delta) and
 * Overview (the page-level "no snapshots yet" check) under the same query
 * key, so it's genuinely one network round trip, not two. */
export function fetchHeroNetWorth(): Promise<NetWorthPoint[]> {
  const params = new URLSearchParams({
    scope: "net",
    granularity: "day",
    from: isoDaysAgo(HERO_DAYS),
  });
  return api.get<NetWorthPoint[]>(`/api/timeseries/networth?${params}`);
}

/** A function, not a constant: the window's `from` bound moves by a day
 * every local midnight, but a plain array literal would freeze it at
 * whatever it was when the module first loaded. Since the bound wasn't
 * part of the key, a query considered "fresh" (within staleTime) kept
 * serving yesterday's HERO_DAYS window after midnight — same request,
 * same key, so TanStack Query never knew to refetch. Including today's
 * local date makes the key itself roll over. */
export function netWorthQueryKey(): readonly [string, string, string] {
  return ["networth", "overview", isoDaysAgo(0)] as const;
}
