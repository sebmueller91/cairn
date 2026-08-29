// Small helpers shared by the Overview cards. Kept local to this directory
// (rather than lib/) since Overview is the only page that owns this shape
// of query — see the ownership note at the top of Overview.tsx.

import { api, type NetWorthPoint } from "../../lib/api";

// The local-day helpers moved to lib/localDate.ts once three copies of them
// existed and one of them (wealth/util.ts) had drifted to UTC. Re-exported
// here so the Overview cards that already import it from this module keep
// working.
import { isoDaysAgo } from "../../lib/localDate";
export { isoDaysAgo };

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

/** The key both the hero and the Overview page mount this query under.
 *
 * Deliberately time-invariant. It used to end in `isoDaysAgo(0)` so the key
 * itself rolled over at local midnight and forced a refetch of a freshly
 * bounded window — which worked, and cost the offline cache everything: the
 * key IndexedDB holds yesterday's answer under is not the key anyone asks
 * for today, so away from home the hero errored instead of showing the last
 * number it knew (lib/queryState.ts documents the general rule). The
 * rollover now comes from `staleTimeWithinLocalDay` instead, and the window
 * bound is computed inside `fetchHeroNetWorth` at fetch time.
 *
 * Still a function rather than a constant, purely so both call sites keep
 * reading the same way. */
export function netWorthQueryKey(): readonly [string, string, number] {
  return ["networth", "overview", HERO_DAYS] as const;
}
