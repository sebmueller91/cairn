// One definition of "what local day is it", shared by every rolling window
// bound in the app. There were three copies of this before — one in
// components/overview/utils.ts, a private duplicate in
// portfolio/ClassDistributionCard.tsx, and an inline `toISOString()` in
// wealth/util.ts that silently disagreed with the other two for an hour or
// two either side of midnight.

/** `YYYY-MM-DD` for a `Date`, read from its *local* fields. `toISOString()`
 * converts to UTC first, which silently steps back a day for anyone in a
 * positive UTC offset (all of Central Europe) during the early hours of
 * the local day — before ~01:00 CET / ~02:00 CEST, "today" would come out
 * as yesterday. */
export function localISODate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/** ISO `YYYY-MM-DD` for `days` ago, in local time — matches the `from`
 * query params the timeseries/attribution endpoints expect.
 *
 * Call this inside a `queryFn`, never while building a query key: a key
 * containing today's date changes at midnight, and the persisted cache the
 * old key pointed at becomes unreachable rather than stale (see the rule in
 * lib/queryState.ts). */
export function isoDaysAgo(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return localISODate(d);
}

/** ISO `YYYY-MM-DD` for `months` ago, in local time. Mirrors
 * `Date.prototype.setMonth`'s own clamping: 31 March minus one month is
 * 3 March, not 28 February — irrelevant for a lower bound on a time series
 * that only ever widens it by a day or two. */
export function isoMonthsAgo(months: number): string {
  const d = new Date();
  d.setMonth(d.getMonth() - months);
  return localISODate(d);
}
