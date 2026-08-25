import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  shouldAnimateCharts,
  CHART_MARGINS,
  axisProps,
  compactTickFormatter,
  dateTickFormatter,
  gridProps,
  valueAxis,
} from "./chartTheme";

interface Datum {
  date: string;
  actual?: number;
  mid?: number;
  low?: number;
  high?: number;
  band?: [number, number];
}

/**
 * The shared ChartTooltip cannot serve this chart: the band's value is a
 * [low, high] tuple, and `Number([low, high])` is NaN — every hover over
 * the projection would read "NaN €". Restricting it with `only` would fix
 * that by hiding the range, which is the one thing the cone exists to
 * show. So the range gets its own row, written as a span rather than as
 * two more series.
 */
function ConeTooltip({
  active,
  payload,
  label,
  formatValue,
  formatLabel,
  historyLabel,
  projectionLabel,
  rangeLabel,
}: {
  active?: boolean;
  payload?: ReadonlyArray<{ payload?: Datum }>;
  label?: string | number;
  formatValue: (n: number) => string;
  formatLabel: (value: string | number) => string;
  historyLabel: string;
  projectionLabel: string;
  rangeLabel: string;
}) {
  const datum = active ? payload?.[0]?.payload : undefined;
  if (!datum) return null;

  const rows: { name: string; value: string; color: string }[] = [];
  if (datum.actual !== undefined) {
    rows.push({
      name: historyLabel,
      value: formatValue(datum.actual),
      color: "var(--accent)",
    });
  }
  if (datum.mid !== undefined && datum.actual === undefined) {
    rows.push({
      name: projectionLabel,
      value: formatValue(datum.mid),
      color: "var(--text-muted)",
    });
    if (datum.low !== undefined && datum.high !== undefined && datum.low !== datum.high) {
      rows.push({
        name: rangeLabel,
        value: `${formatValue(datum.low)} – ${formatValue(datum.high)}`,
        color: "transparent",
      });
    }
  }
  if (rows.length === 0) return null;

  return (
    <div className="rounded-lg border border-border bg-bg-subtle/90 px-3 py-2 text-xs shadow-lg backdrop-blur-glass">
      {label !== undefined && (
        <div className="mb-1.5 font-medium text-text-muted">{formatLabel(label)}</div>
      )}
      <div className="space-y-1">
        {rows.map((row) => (
          <div key={row.name} className="flex items-center gap-2">
            <span
              aria-hidden
              className="size-2 shrink-0 rounded-full"
              style={{ backgroundColor: row.color }}
            />
            <span className="text-text-muted">{row.name}</span>
            <span className="tnum sensitive ml-auto font-medium">{row.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export interface ConePoint {
  date: string;
  low: number;
  mid: number;
  high: number;
}

/**
 * Recorded history, then a projected cone.
 *
 * The visual grammar is the whole point of this component. Everything
 * left of the marker happened; everything right of it is an assumption,
 * and AGENTS.md is explicit that the two must never be rendered alike.
 * So history is a solid accent line, the projection is a dashed muted
 * line inside a translucent band, and a labelled reference line marks
 * exactly where measurement stops. A single smooth exponential drawn in
 * the same stroke as the history would be the most persuasive-looking
 * lie this app is capable of telling.
 *
 * The band is drawn from the pessimistic and optimistic return
 * assumptions rather than from any statistical interval — it is a range
 * of *stated premises*, not a confidence interval, and the card around
 * it says so.
 */
export function ProjectionConeChart({
  history,
  cone,
  seamDate,
  seamLabel,
  historyLabel,
  projectionLabel,
  rangeLabel,
  height = 300,
  formatValue,
}: {
  history: { date: string; value: number }[];
  cone: ConePoint[];
  /** Where recorded data ends and the projection begins. */
  seamDate: string;
  seamLabel: string;
  historyLabel: string;
  projectionLabel: string;
  /** Row label for the low–high span in the tooltip. */
  rangeLabel: string;
  height?: number;
  formatValue: (n: number) => string;
}) {
  const { i18n } = useTranslation();
  const formatDateTick = dateTickFormatter(i18n.language);

  const data = useMemo(() => {
    const byDate = new Map<string, Datum>();
    for (const p of history) byDate.set(p.date, { date: p.date, actual: p.value });
    for (const p of cone) {
      const row = byDate.get(p.date) ?? { date: p.date };
      row.mid = p.mid;
      row.low = p.low;
      row.high = p.high;
      row.band = [p.low, p.high];
      byDate.set(p.date, row);
    }
    // The seam carries both series, so the dashed line and the band start
    // exactly on the last recorded value instead of floating away from it
    // with a visible gap.
    const seam = byDate.get(seamDate);
    if (seam && seam.actual !== undefined && seam.mid === undefined) {
      seam.mid = seam.actual;
      seam.low = seam.actual;
      seam.high = seam.actual;
      seam.band = [seam.actual, seam.actual];
    }
    return [...byDate.values()].sort((a, b) => a.date.localeCompare(b.date));
  }, [history, cone, seamDate]);

  // Every value that actually gets drawn — the band's edges included, or
  // the cone would clip at the top of the plot on an optimistic run.
  const { domain, ticks } = useMemo(
    () =>
      valueAxis(
        data.flatMap((d) =>
          [d.actual, d.low, d.high].filter((v): v is number => v !== undefined),
        ),
      ),
    [data],
  );

  return (
    <>
      <div className="mb-2 flex flex-wrap items-center gap-4 text-xs text-text-muted">
        <span className="flex items-center gap-1.5">
          <span
            className="inline-block h-0.5 w-4 rounded"
            style={{ background: "var(--accent)" }}
            aria-hidden
          />
          {historyLabel}
        </span>
        <span className="flex items-center gap-1.5">
          <span
            className="inline-block h-0 w-4 border-t-2 border-dashed"
            style={{ borderColor: "var(--text-muted)" }}
            aria-hidden
          />
          {projectionLabel}
        </span>
      </div>
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={data} margin={CHART_MARGINS}>
          <defs>
            <linearGradient id="cone-band" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--text-muted)" stopOpacity={0.22} />
              <stop offset="100%" stopColor="var(--text-muted)" stopOpacity={0.06} />
            </linearGradient>
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
            // Money on the value axis, so privacy mode blurs the ticks
            // too — same reasoning as GradientAreaChart.
            tick={{ className: "sensitive", fill: "var(--text-muted)", fontSize: 12 }}
            orientation="right"
            width={56}
            // `["auto", "auto"]` anchors an area chart's axis at zero,
            // which flattens three years of recorded history into a
            // wiggle once the projection reaches six figures. valueAxis
            // is the same padded, nice-stepped scale the wealth curve
            // above already uses, so the two charts agree about how a
            // value axis behaves.
            domain={domain}
            ticks={ticks}
            tickFormatter={compactTickFormatter(i18n.language)}
          />
          <Tooltip
            content={
              <ConeTooltip
                formatValue={formatValue}
                formatLabel={formatDateTick}
                historyLabel={historyLabel}
                projectionLabel={projectionLabel}
                rangeLabel={rangeLabel}
              />
            }
          />
          {/* Drawn first so the lines sit on top of it. */}
          <Area
            isAnimationActive={shouldAnimateCharts()}
            type="monotone"
            dataKey="band"
            stroke="none"
            fill="url(#cone-band)"
            connectNulls
            legendType="none"
            name={projectionLabel}
          />
          <ReferenceLine
            x={seamDate}
            stroke="var(--text-muted)"
            strokeDasharray="2 3"
            label={{
              value: seamLabel,
              position: "insideTopLeft",
              fill: "var(--text-muted)",
              fontSize: 11,
            }}
          />
          <Line
            isAnimationActive={shouldAnimateCharts()}
            type="monotone"
            dataKey="actual"
            name={historyLabel}
            stroke="var(--accent)"
            strokeWidth={2}
            dot={false}
            connectNulls
          />
          <Line
            isAnimationActive={shouldAnimateCharts()}
            type="monotone"
            dataKey="mid"
            name={projectionLabel}
            stroke="var(--text-muted)"
            strokeWidth={1.5}
            strokeDasharray="4 3"
            dot={false}
            connectNulls
          />
        </ComposedChart>
      </ResponsiveContainer>
    </>
  );
}
