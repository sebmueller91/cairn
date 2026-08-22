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

/**
 * Y-axis domain and ticks for a single-value series — a window around the
 * data rather than Recharts' default `[0, "auto"]`.
 *
 * Zero-based is the honest default when the *filled area* is what carries
 * the meaning. Here it isn't: this is a level over time, and at a net worth
 * of 760k a 46k half-year move renders as a flat line pinned to the top of
 * a mostly empty chart — the reader learns nothing the big number above the
 * chart didn't already say. Three things keep the truncation from lying:
 * the gradient fades to fully transparent well before the axis, so there is
 * no solid slab implying a quantity measured from zero; the value axis is
 * always labelled, so the window's start is visible; and zero is never
 * cropped out from below.
 *
 * Bounds are padded, then rounded outward to a round step, so ticks land on
 * 700k / 720k / … rather than 703.417. Ticks are returned rather than left
 * to Recharts, which would space them evenly across the domain and land on
 * arbitrary values again.
 */
export function valueAxis(values: number[]): { domain: [number, number]; ticks: number[] } {
  if (values.length === 0) return { domain: [0, 1], ticks: [0, 1] };

  const min = Math.min(...values);
  const max = Math.max(...values);
  // A flat series has no span to scale to. Fall back to a fraction of its
  // level so it draws down the middle instead of collapsing onto an edge,
  // and to 1 for a series that is flat *at* zero.
  const span = max - min || Math.abs(max) * 0.1 || 1;
  const pad = span * 0.1;
  const lowest = min - pad;
  const highest = max + pad;

  // Aim for four intervals, then widen the step until the grid stops being
  // busy. Rounding the bounds outward can add up to two more intervals, and
  // nine dashed rules on a 280px chart is noise, not orientation.
  let step = niceStep((highest - lowest) / 4);
  let lo = Math.floor(lowest / step) * step;
  let hi = Math.ceil(highest / step) * step;
  while ((hi - lo) / step > 7) {
    step = nextNiceStep(step);
    lo = Math.floor(lowest / step) * step;
    hi = Math.ceil(highest / step) * step;
  }

  // Don't invent negative territory under a series that never goes there…
  if (min >= 0 && lo < 0) lo = 0;
  // …and don't put the waterline off-screen for one that does.
  if (min < 0 && hi < 0) hi = 0;

  const ticks: number[] = [];
  for (let t = lo; t <= hi + step / 2; t += step) ticks.push(Math.round(t * 1e6) / 1e6);

  return { domain: [lo, hi], ticks };
}

/**
 * Round to the nearest 1, 2 or 5 × a power of ten — the steps axis ticks
 * look right on. Nearest rather than upward: rounding 1.4 up to 2 doubles
 * the step, and the bounds then round outward so far that the data occupies
 * barely half the plot — which is the problem this whole function exists to
 * solve, reintroduced one level down.
 */
function niceStep(raw: number): number {
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const normalized = raw / magnitude;
  const factor = normalized < 1.5 ? 1 : normalized < 3.5 ? 2 : normalized < 7.5 ? 5 : 10;
  return factor * magnitude;
}

/** The next round step up: 1 → 2 → 5 → 10. */
function nextNiceStep(step: number): number {
  const magnitude = 10 ** Math.floor(Math.log10(step) + 1e-9);
  const normalized = Math.round(step / magnitude);
  return (normalized === 1 ? 2 : normalized === 2 ? 5 : 10) * magnitude;
}
