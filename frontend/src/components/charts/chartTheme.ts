// Shared Recharts configuration. Everything visual that more than one chart
// needs lives here so the family stays coherent.

import { formatCurrency, formatDate, formatNumber } from "../../lib/format";
import { ASSET_CLASS_COLORS } from "../../lib/assetClasses";

export { ASSET_CLASS_COLORS };
export type { AssetClass } from "../../lib/assetClasses";

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
