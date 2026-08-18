// Shared Recharts configuration. Everything visual that more than one chart
// needs lives here so the family stays coherent.

import { formatCurrency, formatDate, formatNumber } from "../../lib/format";
import { ASSET_CLASS_COLORS } from "../../lib/assetClasses";
import { prefersReducedMotion } from "../../lib/motion";

export { ASSET_CLASS_COLORS };
export type { AssetClass } from "../../lib/assetClasses";

/**
 * Pass to every animated Recharts series as `isAnimationActive`.
 *
 * Recharts drives its entry animation with requestAnimationFrame, which a
 * hidden tab never fires — a chart mounted in a background tab would stay
 * frozen at frame zero (i.e. blank) even after the tab is shown again. It
 * also can't see the CSS reduced-motion kill-switch, being JS-driven. In
 * both cases the chart should simply draw itself finished.
 */
export function shouldAnimateCharts(): boolean {
  return !prefersReducedMotion() && !(typeof document !== "undefined" && document.hidden);
}

/**
 * FIXED — do not change per chart.
 *
 * The planned replay feature draws its own cursor overlay on top of a chart
 * by mapping a timestamp to a pixel x-offset. That maths uses the plot area,
 * which is the container box minus exactly these margins. If one chart drifts
 * to a different margin, its overlay cursor silently lands in the wrong place
 * — a bug that looks like a data problem, not a layout one. Every wrapper in
 * this directory passes CHART_MARGINS verbatim.
 */
export const CHART_MARGINS = {
  top: 8,
  right: 8,
  bottom: 0,
  left: 0,
} as const;

/** Spread onto `<XAxis>` / `<YAxis>`: hairline-free axes, muted ticks. */
export const axisProps = {
  stroke: "var(--text-muted)",
  fontSize: 12,
  tickLine: false,
  axisLine: false,
} as const;

/** Spread onto `<CartesianGrid>`: horizontal rules only, no vertical noise. */
export const gridProps = {
  horizontal: true,
  vertical: false,
  stroke: "var(--border)",
  strokeDasharray: "3 3",
} as const;

// Tick formatters are factories rather than plain functions: the locale
// comes from the caller's `useTranslation()` and must not be read from a
// module-level singleton, or a language switch would leave axes stale.

/** `tickFormatter` for a date axis. */
export function dateTickFormatter(lang: string) {
  return (value: string | number) => formatDate(String(value), lang);
}

/** `tickFormatter` for a value axis — compact, so "1.2 Mio. €" fits. */
export function compactTickFormatter(lang: string) {
  return (value: number) =>
    formatNumber(value, lang, {
      notation: "compact",
      maximumFractionDigits: 1,
    });
}

/** `tickFormatter` / tooltip formatter for full currency amounts. */
export function currencyFormatter(lang: string) {
  return (value: number) => formatCurrency(value, lang);
}

/**
 * The six performance-attribution components (spec 4.5), keyed by the API's
 * field names so a caller can index straight off the response object.
 */
export const ATTRIBUTION_COLORS = {
  deposits_withdrawals: "var(--attr-deposits)",
  income: "var(--attr-income)",
  costs: "var(--attr-costs)",
  valuation_adjustments: "var(--attr-valuation)",
  fx_effect: "var(--attr-fx)",
  market_gains_losses: "var(--attr-market)",
} as const;

export type AttributionKey = keyof typeof ATTRIBUTION_COLORS;

/**
 * Categorical palette for charts whose slices are *entities* — individual
 * instruments — rather than asset classes, which have their own fixed
 * colours above.
 *
 * Stepped in OKLCH and run through the palette validator for both surfaces:
 * every hue inside its mode's lightness band, chroma above the gray floor,
 * and adjacent pairs separated under deuteranopia and tritanopia as well as
 * normal vision. Hues are interleaved around the wheel and alternate in
 * lightness precisely so neighbours in a legend stay distinguishable.
 *
 * Assign in this order and never cycle: reusing a hue for a ninth slice
 * makes two different holdings look like the same one. Anything past the
 * end of this list belongs in a single neutral "other" slice.
 */
export const SERIES_COLORS = [
  "var(--series-1)",
  "var(--series-2)",
  "var(--series-3)",
  "var(--series-4)",
  "var(--series-5)",
  "var(--series-6)",
  "var(--series-7)",
] as const;

/** The catch-all slice. Deliberately not a palette hue — "other" is not an
 * entity and must not read as one. */
export const OTHER_COLOR = "var(--text-muted)";
