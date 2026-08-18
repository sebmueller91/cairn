import { formatPercent } from "../../lib/format";

export type LegendItem = {
  key: string;
  label: string;
  color: string;
  value: number;
};

/**
 * Colour key for a donut or stacked chart. Shares of the total are computed
 * here rather than passed in, so a legend can never disagree with the chart
 * it labels about what 100% is.
 *
 * Rows are not sorted — the caller's order is the chart's slice order, and a
 * legend that reordered them would stop being a key.
 */
export function ChartLegend({
  items,
  language,
  formatValue,
  className = "",
}: {
  items: LegendItem[];
  language: string;
  /** Omit to show only the share, which is what a compact card wants. */
  formatValue?: (n: number) => string;
  className?: string;
}) {
  const total = items.reduce((sum, item) => sum + item.value, 0);

  return (
    <ul className={`space-y-1 text-xs ${className}`}>
      {items.map((item) => (
        <li key={item.key} className="flex items-center gap-1.5">
          <span
            className="size-2 shrink-0 rounded-full"
            style={{ backgroundColor: item.color }}
            aria-hidden
          />
          <span className="truncate text-text-muted">{item.label}</span>
          <span className="tnum ml-auto shrink-0 pl-1 text-text">
            {formatValue
              ? formatValue(item.value)
              : total > 0
                ? formatPercent(item.value / total, language)
                : "—"}
          </span>
        </li>
      ))}
    </ul>
  );
}
