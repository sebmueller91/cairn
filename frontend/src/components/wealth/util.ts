// Small shared bits of the Wealth page. Kept out of the components so the
// period vocabulary has exactly one definition across the four cards.

/** Ranges the Wealth page offers. `MAX` means "everything on record". */
export type Period = "7D" | "1M" | "3M" | "6M" | "1Y" | "5Y" | "MAX";

export const PERIODS: readonly Period[] = ["7D", "1M", "3M", "6M", "1Y", "5Y", "MAX"];

export type Granularity = "day" | "week" | "month";

/**
 * A period as query parameters. Wide ranges ask for coarser buckets rather
 * than shipping thousands of daily points to the browser (ADR 0004) — the
 * same lever Dashboard.tsx pulls, at the coarser step ladder this page's
 * five buttons need. `from: undefined` is how `MAX` says "no lower bound".
 */
export function rangeFor(period: Period): {
  from?: string;
  granularity: Granularity;
} {
  const now = new Date();
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  const daysBack = (n: number) => {
    const d = new Date(now);
    d.setDate(d.getDate() - n);
    return iso(d);
  };
  const monthsBack = (n: number) => {
    const d = new Date(now);
    d.setMonth(d.getMonth() - n);
    return iso(d);
  };

  switch (period) {
    case "7D":
      // The only range where a single day's move is the whole story: prices
      // land once a day, so a week is eight points and every one of them is
      // a real close rather than a bucket average.
      return { from: daysBack(7), granularity: "day" };
    case "1M":
      return { from: monthsBack(1), granularity: "day" };
    case "3M":
      return { from: monthsBack(3), granularity: "day" };
    case "6M":
      return { from: monthsBack(6), granularity: "week" };
    case "1Y":
      return { from: monthsBack(12), granularity: "week" };
    case "5Y":
      // Still weekly rather than monthly: ~260 points is nothing for the
      // chart, and it keeps the shape of a drawdown visible. Monthly
      // buckets smooth exactly the detail this range exists to show —
      // MAX is where the ladder finally gives that up.
      return { from: monthsBack(60), granularity: "week" };
    case "MAX":
      return { granularity: "month" };
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
