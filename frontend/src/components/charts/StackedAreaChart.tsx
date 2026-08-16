// Composition over time — one band per asset class.
//
// NEGATIVE SERIES (LIABILITY): handled by `stackOffset="sign"` rather than a
// separate un-stacked Area. Recharts' default offset ("none") accumulates
// sequentially, so a negative series subtracts from the running total and
// its band gets drawn *through* the positive ones. With "sign", positives
// stack upward from zero and negatives stack downward from zero, which is
// exactly the "assets above, debt below" reading we want — and it keeps the
// LIABILITY band inside the same tooltip and legend as everything else,
// which a separately-plotted Area would not.

import { useId } from "react";
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
} from "./chartTheme";

export type StackSeries = {
  /** Property name on each row of `data`. */
  key: string;
  color: string;
  label: string;
};

/** Stacked composition over time. Series render bottom-up in array order. */
export function StackedAreaChart({
  data,
  series,
  height = 280,
  formatValue,
}: {
  data: Array<{ date: string } & Record<string, string | number>>;
  series: StackSeries[];
  height?: number;
  formatValue: (n: number) => string;
}) {
  const { i18n } = useTranslation();
  const idBase = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const formatDateTick = dateTickFormatter(i18n.language);

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={CHART_MARGINS} stackOffset="sign">
        <defs>
          {series.map((s) => (
            <linearGradient
              key={s.key}
              id={`stack-${idBase}-${s.key}`}
              x1="0"
              y1="0"
              x2="0"
              y2="1"
            >
              <stop offset="0%" stopColor={s.color} stopOpacity={0.55} />
              <stop offset="100%" stopColor={s.color} stopOpacity={0.15} />
            </linearGradient>
          ))}
        </defs>
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
          tickFormatter={compactTickFormatter(i18n.language)}
        />
        {/* Zero is load-bearing here — it is the assets/debt waterline. */}
        <ReferenceLine y={0} stroke="var(--border)" />
        <Tooltip
          content={
            <ChartTooltip
              formatValue={formatValue}
              formatLabel={(l) => formatDateTick(l)}
            />
          }
        />
        {series.map((s) => (
          <Area
            isAnimationActive={shouldAnimateCharts()}
            key={s.key}
            type="monotone"
            dataKey={s.key}
            name={s.label}
            stackId="1"
            stroke={s.color}
            strokeWidth={1}
            fill={`url(#stack-${idBase}-${s.key})`}
            dot={false}
          />
        ))}
      </AreaChart>
    </ResponsiveContainer>
  );
}
