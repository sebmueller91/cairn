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

/** Height per category row, and the room the value axis needs below them. */
const ROW_HEIGHT = 34;
const VALUE_AXIS_HEIGHT = 28;
/** Width reserved for the category labels. "Marktgewinne/-verluste" is the
 *  longest of them and needs about this much at 11px. */
const CATEGORY_AXIS_WIDTH = 148;

/** Attribution waterfall: what moved the number, component by component.
 *
 * Laid out horizontally — categories down the left, value along the
 * bottom. Vertically it could not work: the buckets are long German
 * compounds ("Bewertungsänderungen", "Marktgewinne/-verluste") and eight
 * of them across a card's width leaves roughly 100px each, so the labels
 * had to be rotated, and rotated they still overlapped their neighbours
 * by ~25px and overflowed the SVG's own height by 7px, clipping the
 * descenders. Steeper angles and a taller axis only move the width at
 * which that starts; on a phone nothing fits at all. Horizontal rows
 * read straight, cannot collide, and behave the same at every width.
 */
export function BarWaterfall({
  data,
  formatValue,
}: {
  data: WaterfallBar[];
  formatValue: (n: number) => string;
}) {
  const { i18n } = useTranslation();
  const height = data.length * ROW_HEIGHT + VALUE_AXIS_HEIGHT;

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} layout="vertical" margin={CHART_MARGINS}>
        {/* Grid lines now run with the value axis, which is horizontal. */}
        <CartesianGrid {...gridProps} horizontal={false} vertical />
        <XAxis
          type="number"
          {...axisProps}
          // Money moved to this axis with the layout flip, and privacy
          // mode has to follow it: leaving `sensitive` on the category
          // axis would blur the harmless bucket names and print the
          // amounts in the clear.
          tick={{ className: "sensitive", fill: "var(--text-muted)", fontSize: 12 }}
          height={VALUE_AXIS_HEIGHT}
          tickFormatter={compactTickFormatter(i18n.language)}
        />
        <YAxis
          type="category"
          dataKey="name"
          {...axisProps}
          // Every bucket keeps its label; a waterfall with a step missing
          // does not add up on screen even though the numbers do.
          interval={0}
          width={CATEGORY_AXIS_WIDTH}
          fontSize={11}
        />
        <Tooltip
          cursor={{ fill: "var(--border)", fillOpacity: 0.4 }}
          content={
            <ChartTooltip formatValue={formatValue} only={["delta"]} hideName />
          }
        />
        <Bar dataKey="base" stackId="w" fill="transparent" isAnimationActive={false} />
        <Bar dataKey="delta" stackId="w" radius={[0, 4, 4, 0]} isAnimationActive={shouldAnimateCharts()}>
          {data.map((bar) => (
            <Cell key={bar.name} fill={bar.color} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
