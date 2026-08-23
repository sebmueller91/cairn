import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { getAllocationTimeseries } from "../../lib/api";
import { formatCurrency } from "../../lib/format";
import {
  ASSET_CLASSES,
  ASSET_CLASS_COLORS,
  assetClassLabelKey,
} from "../../lib/assetClasses";
import { GlassCard } from "../ui/GlassCard";
import { Skeleton } from "../ui/Skeleton";
import { DonutChart, type DonutSlice } from "../charts/DonutChart";
import { ChartLegend, type LegendItem } from "../charts/ChartLegend";
import { isoDaysAgo } from "./utils";
import { useIsLoading } from "../../lib/queryState";

/** Mini allocation donut for the latest snapshot. LIABILITY is excluded —
 * a donut can't render a negative slice — and shown as a small debt line
 * underneath instead.
 *
 * The total sits beside the ring rather than inside it: a six-figure sum in
 * a 180px donut hole overflows its own chart, and the hole is too small to
 * hold a number this app routinely shows to the cent. */
export function ClassMixCard() {
  const { t, i18n } = useTranslation("overview");

  // The `from` bound is part of the key (not just the queryFn) for the same
  // reason as netWorthQueryKey — otherwise a cached "fresh" query keeps
  // answering yesterday's 14-day window after local midnight.
  const from = isoDaysAgo(14);
  const { data, isPending, isError } = useQuery({
    queryKey: ["allocation-timeseries", "overview", from],
    queryFn: () => getAllocationTimeseries({ from, granularity: "day" }),
  });
  const pending = useIsLoading(isPending);

  if (pending) {
    return (
      <GlassCard>
        <Skeleton className="h-4 w-28" />
        <Skeleton className="mt-6 size-32 rounded-full" />
      </GlassCard>
    );
  }

  if (isError) {
    return (
      <GlassCard>
        <div className="mb-2 text-sm text-text-muted">{t("classMix.title")}</div>
        <p className="text-sm text-text-muted">{t("common:status.error")}</p>
      </GlassCard>
    );
  }

  const points = data ?? [];
  const latest = points[points.length - 1];

  const slices: DonutSlice[] = latest
    ? ASSET_CLASSES.filter((c) => c !== "LIABILITY")
        .map((c) => ({
          name: t(`common:${assetClassLabelKey(c)}`),
          value: Number(latest.values[c] ?? "0"),
          color: ASSET_CLASS_COLORS[c],
        }))
        .filter((s) => s.value > 0)
        // Largest first, in the ring and in the legend alike. ASSET_CLASSES
        // order is the right default where slices must stay put between
        // frames (the replay's mix bar); a static card reads better ranked,
        // and sorting the slices rather than the legend keeps the two in
        // step — a legend in a different order than its chart stops being
        // a key.
        .sort((a, b) => b.value - a.value)
    : [];

  const total = slices.reduce((sum, s) => sum + s.value, 0);
  const liability = latest ? Number(latest.values.LIABILITY ?? "0") : 0;
  const legend: LegendItem[] = slices.map((s) => ({
    key: s.name,
    label: s.name,
    color: s.color,
    value: s.value,
  }));

  return (
    <GlassCard>
      <div className="text-sm text-text-muted">{t("classMix.title")}</div>
      {slices.length === 0 ? (
        <p className="py-10 text-center text-sm text-text-muted">
          {t("common:status.empty")}
        </p>
      ) : (
        <div className="mt-3 flex items-start gap-4">
          <div className="w-[128px] shrink-0">
            <DonutChart
              data={slices}
              height={128}
              formatValue={(n) => formatCurrency(n, i18n.language)}
            />
          </div>
          <div className="min-w-0 flex-1">
            <div className="tnum sensitive text-lg font-[650] leading-tight tracking-tight">
              {formatCurrency(total, i18n.language)}
            </div>
            <div className="text-xs text-text-muted">{t("classMix.grossLabel")}</div>
            {liability < 0 && (
              <div className="tnum mt-0.5 text-xs text-negative">
                <span className="sensitive">{formatCurrency(liability, i18n.language)}</span>{" "}
                {t("classMix.liabilities")}
              </div>
            )}
            <ChartLegend items={legend} language={i18n.language} className="mt-2.5" />
          </div>
        </div>
      )}
    </GlassCard>
  );
}
