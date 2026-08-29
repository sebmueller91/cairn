// Small shared bits of the Wealth page. Kept out of the components so the
// period vocabulary has exactly one definition across the four cards.

import { isoDaysAgo, isoMonthsAgo } from "../../lib/localDate";

/** Ranges the Wealth page offers. `MAX` means "everything on record". */
export type Period = "7D" | "1M" | "3M" | "6M" | "1Y" | "5Y" | "MAX";

export const PERIODS: readonly Period[] = ["7D", "1M", "3M", "6M", "1Y", "5Y", "MAX"];

export type Granularity = "day" | "week" | "month";

/**
 * How coarse a period's buckets are. Wide ranges ask for coarser buckets
 * rather than shipping thousands of daily points to the browser (ADR 0004)
 * — the same lever Dashboard.tsx pulls, at the coarser step ladder this
 * page's five buttons need.
 *
 * Split out from {@link rangeFor} because it is a pure function of the
 * period with no dependence on the current date, which makes it safe to put
 * in a query key — the `from` bound is not (see lib/queryState.ts).
 */
export function granularityFor(period: Period): Granularity {
  switch (period) {
    case "7D":
      // The only range where a single day's move is the whole story: prices
      // land once a day, so a week is eight points and every one of them is
      // a real close rather than a bucket average.
      return "day";
    case "1M":
    case "3M":
      return "day";
    case "6M":
    case "1Y":
      return "week";
    case "5Y":
      // Still weekly rather than monthly: ~260 points is nothing for the
      // chart, and it keeps the shape of a drawdown visible. Monthly
      // buckets smooth exactly the detail this range exists to show —
      // MAX is where the ladder finally gives that up.
      return "week";
    case "MAX":
      return "month";
  }
}

/**
 * A period as query parameters. `from: undefined` is how `MAX` says "no
 * lower bound".
 *
 * Call this inside a `queryFn`, so the bound is recomputed on every fetch.
 * The bounds used to be built from `toISOString()`, i.e. UTC, so this page
 * rolled its window over an hour or two before the Overview cards did —
 * both are on the local day now, via lib/localDate.ts.
 */
export function rangeFor(period: Period): {
  from?: string;
  granularity: Granularity;
} {
  const granularity = granularityFor(period);
  switch (period) {
    case "7D":
      return { from: isoDaysAgo(7), granularity };
    case "1M":
      return { from: isoMonthsAgo(1), granularity };
    case "3M":
      return { from: isoMonthsAgo(3), granularity };
    case "6M":
      return { from: isoMonthsAgo(6), granularity };
    case "1Y":
      return { from: isoMonthsAgo(12), granularity };
    case "5Y":
      return { from: isoMonthsAgo(60), granularity };
    case "MAX":
      return { granularity };
  }
}

// Mirrors the private table in lib/format.ts. en-GB, not en-US, for the same
// reason: it agrees with de-DE on day-before-month, so a date is never
// ambiguous between the two languages this app ships.
const INTL_LOCALE: Record<string, string> = {
  de: "de-DE",
  en: "en-GB",
};

/**
 * "Mar 2024" / "März 2024" — the resolution a milestone or a replay frame
 * actually carries. A full dd.mm.yyyy would imply a precision that a
 * month-bucketed series does not have.
 */
export function formatMonthYear(value: string | Date, lang: string): string {
  const date = typeof value === "string" ? new Date(value) : value;
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(INTL_LOCALE[lang] ?? "de-DE", {
    year: "numeric",
    month: "short",
  }).format(date);
}

export interface FrameIndices {
  /** Bucket at or before the playhead. */
  lower: number;
  /** The next bucket, for interpolating between them. */
  upper: number;
  /** 0..1 position between `lower` and `upper`. */
  t01: number;
  /** Nearest bucket — for labels, where interpolating would be false precision. */
  snap: number;
}

/**
 * Safe indices into a replay series for a (possibly stale) playhead.
 *
 * The playhead is React state while the series comes from props, so changing
 * the period shrinks the series while the old frame is still in state. The
 * clamping effect only runs *after* that render, which means every index has
 * to be clamped here or the render in between reads past the end of the
 * array. That is not hypothetical: it blanked the page whenever a shorter,
 * already-cached range was selected with the playhead near the end.
 *
 * An empty series yields zeros; the caller must still not index into it.
 */
export function frameIndices(frame: number, total: number): FrameIndices {
  if (total <= 0) return { lower: 0, upper: 0, t01: 0, snap: 0 };
  const max = total - 1;
  const clamped = Math.min(Math.max(frame, 0), max);
  const lower = Math.min(Math.floor(clamped), max);
  return {
    lower,
    upper: Math.min(lower + 1, max),
    t01: clamped - lower,
    snap: Math.min(Math.round(clamped), max),
  };
}
