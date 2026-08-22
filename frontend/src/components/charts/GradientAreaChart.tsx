import { useId, useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
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
  valueAxis,
} from "./chartTheme";

// `useTranslation` here is only ever read for `i18n.language` — the wrapper
// holds no copy of its own, it just needs the locale to format axis ticks.

/** Single-series time chart: 2px line over a gradient that fades to nothing.
 *
 * The value axis is scaled to the data, not to zero — see `valueAxis`. A
 * series that goes negative gets a zero rule drawn under it. */
export function GradientAreaChart({
  data,
  color = "var(--accent)",
  height = 280,
  formatValue,
}: {
  data: { date: string; value: number }[];
  color?: string;
  height?: number;
  formatValue: (n: number) => string;
}) {
  const { i18n } = useTranslation();
  const gradientId = `area-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const formatDateTick = dateTickFormatter(i18n.language);
  const { domain, ticks } = useMemo(() => valueAxis(data.map((d) => d.value)), [data]);
  const crossesZero = domain[0] < 0;

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={CHART_MARGINS}>
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.35} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid {...gridProps} />
        <XAxis
          dataKey="date"
          {...axisProps}
          // Sparse by pixel distance, not by index: a 5Y monthly series and
          // a 1M daily series then look equally uncrowded.
          minTickGap={44}
          interval="preserveStartEnd"
          tickFormatter={formatDateTick}
        />
        <YAxis
          {...axisProps}
          // Money on the value axis, so privacy mode blurs the ticks too;
          // an unblurred axis would give the hidden figures away.
          tick={{ className: "sensitive", fill: "var(--text-muted)", fontSize: 12 }}
          orientation="right"
          width={56}
          domain={domain}
          ticks={ticks}
          tickFormatter={compactTickFormatter(i18n.language)}
        />
        {crossesZero && (
          <ReferenceLine y={0} stroke="var(--text-muted)" strokeWidth={1} />
        )}
        <Tooltip
          content={
            <ChartTooltip
              formatValue={formatValue}
              formatLabel={(l) => formatDateTick(l)}
              hideName
            />
          }
        />
        <Area
          isAnimationActive={shouldAnimateCharts()}
          type="monotone"
          dataKey="value"
          stroke={color}
          strokeWidth={2}
          fill={`url(#${gradientId})`}
          dot={false}
          activeDot={{ r: 3, strokeWidth: 0 }}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
