import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ChartTooltip } from "./ChartTooltip";
import {
  shouldAnimateCharts,
  CHART_MARGINS,
  axisProps,
  compactTickFormatter,
  dateTickFormatter,
  gridProps,
} from "./chartTheme";

/**
 * Two series on one axis — portfolio vs. benchmark. Makes no assumption
 * about the domain, so it works equally for EUR values and base-100 indices.
 */
export function LineCompareChart({
  primary,
  secondary,
  primaryLabel,
  secondaryLabel,
  height = 280,
  formatValue,
}: {
  primary: { date: string; value: number }[];
  secondary?: { date: string; value: number }[];
  primaryLabel: string;
  secondaryLabel?: string;
  height?: number;
  formatValue: (n: number) => string;
}) {
  const { i18n } = useTranslation();
  const formatDateTick = dateTickFormatter(i18n.language);

  // Merged on date rather than passed as two `data` props, so the tooltip
  // shows both series for the hovered point instead of only the hit one.
  const data = useMemo(() => {
    const byDate = new Map<string, { date: string; a?: number; b?: number }>();
    for (const p of primary) byDate.set(p.date, { date: p.date, a: p.value });
    for (const p of secondary ?? []) {
      const row = byDate.get(p.date);
      if (row) row.b = p.value;
      else byDate.set(p.date, { date: p.date, b: p.value });
    }
    return [...byDate.values()].sort((x, y) => x.date.localeCompare(y.date));
  }, [primary, secondary]);

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={CHART_MARGINS}>
        <CartesianGrid {...gridProps} />
        <XAxis
          dataKey="date"
          {...axisProps}
          minTickGap={44}
          interval="preserveStartEnd"
          tickFormatter={formatDateTick}
        />
        <YAxis
          {...axisProps}
          orientation="right"
          width={56}
          domain={["auto", "auto"]}
          tickFormatter={compactTickFormatter(i18n.language)}
        />
        <Tooltip
          content={
            <ChartTooltip
              formatValue={formatValue}
              formatLabel={(l) => formatDateTick(l)}
            />
          }
        />
        <Line
          isAnimationActive={shouldAnimateCharts()}
          type="monotone"
          dataKey="a"
          name={primaryLabel}
          stroke="var(--accent)"
          strokeWidth={2}
          dot={false}
          connectNulls
        />
        {secondary && (
          <Line
            isAnimationActive={shouldAnimateCharts()}
            type="monotone"
            dataKey="b"
            name={secondaryLabel}
            stroke="var(--text-muted)"
            strokeWidth={1.5}
            strokeDasharray="4 3"
            dot={false}
            connectNulls
          />
        )}
      </LineChart>
    </ResponsiveContainer>
  );
}
