// Stacked +/- bar chart: the six attribution components (spec 4.3), one bar
// per period. Recharts directly rather than StackedAreaChart — that wrapper
// is Area-based and shaped for continuous series, not discrete per-month
// bars — but it still follows chartTheme.ts (axisProps/gridProps/margins)
// and ChartTooltip so it reads as one family with the rest of the charts.
import { useTranslation } from "react-i18next";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { AttributionPeriod } from "../../lib/api";
import { ChartTooltip } from "../charts/ChartTooltip";
import {
  shouldAnimateCharts,
  ATTRIBUTION_COLORS,
  CHART_MARGINS,
  axisProps,
  compactTickFormatter,
  currencyFormatter,
  gridProps,
  type AttributionKey,
} from "../charts/chartTheme";

const SERIES: AttributionKey[] = [
  "deposits_withdrawals",
  "income",
  "costs",
  "valuation_adjustments",
  "fx_effect",
  "market_gains_losses",
];

// Mirrors lib/format.ts's locale mapping — that module doesn't export it,
// and we only need a short month/year tick label here.
const INTL_LOCALE: Record<string, string> = { de: "de-DE", en: "en-GB" };

function periodLabel(dateStr: string, granularity: "month" | "year", lang: string): string {
  const d = new Date(dateStr);
  if (granularity === "year") return String(d.getUTCFullYear());
  return new Intl.DateTimeFormat(INTL_LOCALE[lang] ?? "de-DE", {
    month: "short",
    year: "2-digit",
    timeZone: "UTC",
  }).format(d);
}

export function MonthlyCompositionChart({
  periods,
  granularity,
}: {
  periods: AttributionPeriod[];
  granularity: "month" | "year";
}) {
  const { t, i18n } = useTranslation("performance");
  const formatValue = currencyFormatter(i18n.language);

  const data = periods.map((p) => ({
    label: periodLabel(p.start_date, granularity, i18n.language),
    deposits_withdrawals: Number(p.deposits_withdrawals),
    income: Number(p.income),
    costs: Number(p.costs),
    valuation_adjustments: Number(p.valuation_adjustments),
    fx_effect: Number(p.fx_effect),
    market_gains_losses: Number(p.market_gains_losses),
  }));

  return (
    <div>
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={data} margin={CHART_MARGINS} stackOffset="sign">
          <CartesianGrid {...gridProps} />
          <XAxis dataKey="label" {...axisProps} minTickGap={20} interval="preserveStartEnd" />
          <YAxis
            {...axisProps}
            orientation="right"
            width={56}
            tickFormatter={compactTickFormatter(i18n.language)}
          />
          {/* Zero is load-bearing: it's where deposits/gains flip to costs/losses. */}
          <ReferenceLine y={0} stroke="var(--border)" />
          <Tooltip
            cursor={{ fill: "var(--border)", fillOpacity: 0.4 }}
            content={<ChartTooltip formatValue={formatValue} />}
          />
          {SERIES.map((key) => (
            <Bar
              isAnimationActive={shouldAnimateCharts()}
              key={key}
              dataKey={key}
              name={t(`attribution.buckets.${key}`)}
              stackId="a"
              fill={ATTRIBUTION_COLORS[key]}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-text-muted">
        {SERIES.map((key) => (
          <div key={key} className="flex items-center gap-1.5">
            <span
              aria-hidden
              className="size-2 shrink-0 rounded-full"
              style={{ background: ATTRIBUTION_COLORS[key] }}
            />
            {t(`attribution.buckets.${key}`)}
          </div>
        ))}
      </div>
    </div>
  );
}
