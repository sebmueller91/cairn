// Waterfall via the invisible-base trick.
//
// Recharts has no waterfall chart. The standard workaround is two stacked
// Bar series sharing one stackId: a transparent `base` that lifts the bar to
// where it should start, and a visible `delta` that is the actual magnitude.
// So a step running from 120k to 135k is `{ base: 120000, delta: 15000 }`;
// a step falling from 135k to 130k is `{ base: 130000, delta: 5000 }` — the
// base is always the *lower* of the two edges, and the sign lives in the
// colour, not the geometry.
//
// The caller precomputes base/delta because only it knows the running total
// and whether a bar is a total column (base 0) or a step. The tooltip is
// filtered to the delta series so the invisible base never shows up in it.

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useTranslation } from "react-i18next";
import { ChartTooltip } from "./ChartTooltip";
import {
  shouldAnimateCharts,
  CHART_MARGINS,
  axisProps,
  compactTickFormatter,
  gridProps,
} from "./chartTheme";

export type WaterfallBar = {
  name: string;
  /** Lower edge of the bar; 0 for a full-height total column. */
  base: number;
  /** Bar height — always positive; direction is carried by `color`. */
  delta: number;
  color: string;
};

/** Attribution waterfall: what moved the number, component by component. */
export function BarWaterfall({
  data,
  height = 280,
  formatValue,
}: {
  data: WaterfallBar[];
  height?: number;
  formatValue: (n: number) => string;
}) {
  const { i18n } = useTranslation();

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={CHART_MARGINS}>
        <CartesianGrid {...gridProps} />
        {/* Every bar must keep its label (interval 0), but the category
            names are whole words — "Bewertungsänderungen" — so they only
            fit on an angle. The extra height is the axis's own, leaving
            CHART_MARGINS untouched. */}
        <XAxis
          dataKey="name"
          {...axisProps}
          interval={0}
          angle={-30}
          textAnchor="end"
          height={72}
          fontSize={11}
        />
        <YAxis
          {...axisProps}
          // Money on the value axis, so privacy mode blurs the ticks too;
          // an unblurred axis would give the hidden figures away.
          tick={{ className: "sensitive", fill: "var(--text-muted)", fontSize: 12 }}
          orientation="right"
          width={56}
          tickFormatter={compactTickFormatter(i18n.language)}
        />
        <Tooltip
          cursor={{ fill: "var(--border)", fillOpacity: 0.4 }}
          content={
            <ChartTooltip formatValue={formatValue} only={["delta"]} hideName />
          }
        />
        <Bar dataKey="base" stackId="w" fill="transparent" isAnimationActive={false} />
        <Bar dataKey="delta" stackId="w" radius={[4, 4, 0, 0]} isAnimationActive={shouldAnimateCharts()}>
          {data.map((bar) => (
            <Cell key={bar.name} fill={bar.color} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
