// Attribution tab: fixes the old page's habit of only ever showing the
// latest period. Chart 1 plots every period returned by the API; chart 2
// sums those same periods into a single cumulative waterfall for the whole
// visible range, so the two charts always agree with each other.
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { BarChart3 } from "lucide-react";
import { api, type AttributionResponse } from "../../lib/api";
import { formatDate } from "../../lib/format";
import { GlassCard } from "../ui/GlassCard";
import { SegmentedControl } from "../ui/SegmentedControl";
import { Skeleton } from "../ui/Skeleton";
import { EmptyState } from "../ui/EmptyState";
import { BarWaterfall, type WaterfallBar } from "../charts/BarWaterfall";
import { currencyFormatter } from "../charts/chartTheme";
import { MonthlyCompositionChart } from "./MonthlyCompositionChart";

type Granularity = "month" | "year";

// The six components summed across the whole range (spec 4.3):
//   Δ wealth = deposits/withdrawals + market gains/losses + income
//              − costs + valuation adjustments + FX effect
// `costs` already carries its own (negative) sign from the API — see
// backend/app/attribution_service.py — so every bucket is just added
// straight through; the sign alone decides the bar's colour.
const STEPS = [
  "deposits_withdrawals",
  "income",
  "costs",
  "valuation_adjustments",
  "fx_effect",
  "market_gains_losses",
] as const;

export function AttributionTab() {
  const { t, i18n } = useTranslation("performance");
  const [granularity, setGranularity] = useState<Granularity>("month");

  const { data, isLoading } = useQuery({
    queryKey: ["attribution", granularity],
    queryFn: () => api.get<AttributionResponse>(`/api/attribution?granularity=${granularity}`),
  });

  // Memoized so the waterfall's useMemo below sees a stable reference
  // instead of a fresh `[]` on every render `data` is undefined.
  const periods = useMemo(() => data?.periods ?? [], [data]);
  const formatValue = currencyFormatter(i18n.language);

  const waterfallBars = useMemo<WaterfallBar[]>(() => {
    if (periods.length === 0) return [];

    const totals = { deposits_withdrawals: 0, income: 0, costs: 0, valuation_adjustments: 0, fx_effect: 0, market_gains_losses: 0 };
    for (const p of periods) {
      for (const key of STEPS) totals[key] += Number(p[key]);
    }

    const startValue = Number(periods[0].start_value);
    const endValue = Number(periods[periods.length - 1].end_value);

    const bars: WaterfallBar[] = [
      { name: t("attribution.start"), base: 0, delta: startValue, color: "var(--text-muted)" },
    ];
    let cumulative = startValue;
    for (const key of STEPS) {
      const amount = totals[key];
      const base = Math.min(cumulative, cumulative + amount);
      bars.push({
        name: t(`attribution.buckets.${key}`),
        base,
        delta: Math.abs(amount),
        color: amount >= 0 ? "var(--positive)" : "var(--negative)",
      });
      cumulative += amount;
    }
    bars.push({ name: t("attribution.end"), base: 0, delta: endValue, color: "var(--text-muted)" });
    return bars;
  }, [periods, t]);

  const granularityOptions = [
    { value: "month" as const, label: t("attribution.granularity.month") },
    { value: "year" as const, label: t("attribution.granularity.year") },
  ];

  return (
    <div className="space-y-6">
      <GlassCard>
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <h2 className="font-medium">{t("attribution.composition.title")}</h2>
          <SegmentedControl options={granularityOptions} value={granularity} onChange={setGranularity} />
        </div>
        {isLoading ? (
          <Skeleton className="h-[280px] w-full" />
        ) : periods.length === 0 ? (
          <EmptyState icon={<BarChart3 className="size-8" aria-hidden />} title={t("noData")} />
        ) : (
          <MonthlyCompositionChart periods={periods} granularity={granularity} />
        )}
      </GlassCard>

      <GlassCard>
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <h2 className="font-medium">{t("attribution.waterfall.title")}</h2>
          {periods.length > 0 && (
            <div className="text-xs text-text-muted">
              {formatDate(periods[0].start_date, i18n.language)} –{" "}
              {formatDate(periods[periods.length - 1].end_date, i18n.language)}
            </div>
          )}
        </div>
        {isLoading ? (
          <Skeleton className="h-[280px] w-full" />
        ) : waterfallBars.length === 0 ? (
          <EmptyState icon={<BarChart3 className="size-8" aria-hidden />} title={t("noData")} />
        ) : (
          <BarWaterfall data={waterfallBars} formatValue={formatValue} />
        )}
      </GlassCard>
    </div>
  );
}
