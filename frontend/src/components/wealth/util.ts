// Small shared bits of the Wealth page. Kept out of the components so the
// period vocabulary has exactly one definition across the four cards.

/** Ranges the Wealth page offers. `MAX` means "everything on record". */
export type Period = "1M" | "3M" | "6M" | "1Y" | "MAX";

export const PERIODS: readonly Period[] = ["1M", "3M", "6M", "1Y", "MAX"];

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
  const monthsBack = (n: number) => {
    const d = new Date(now);
    d.setMonth(d.getMonth() - n);
    return iso(d);
  };

  switch (period) {
    case "1M":
      return { from: monthsBack(1), granularity: "day" };
    case "3M":
      return { from: monthsBack(3), granularity: "day" };
    case "6M":
      return { from: monthsBack(6), granularity: "week" };
    case "1Y":
      return { from: monthsBack(12), granularity: "week" };
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
