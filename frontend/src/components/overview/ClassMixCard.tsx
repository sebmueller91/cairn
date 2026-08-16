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
import { isoDaysAgo } from "./utils";

/** Mini allocation donut for the latest snapshot. LIABILITY is excluded —
 * a donut can't render a negative slice — and shown as a small debt line
 * underneath instead. */
export function ClassMixCard() {
  const { t, i18n } = useTranslation("overview");

  const { data, isLoading, isError } = useQuery({
    queryKey: ["allocation-timeseries", "overview"],
    queryFn: () => getAllocationTimeseries({ from: isoDaysAgo(14), granularity: "day" }),
  });

  if (isLoading) {
    return (
      <GlassCard>
        <Skeleton className="h-4 w-28" />
        <Skeleton className="mx-auto mt-6 size-36 rounded-full" />
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
    : [];

  const total = slices.reduce((sum, s) => sum + s.value, 0);
  const liability = latest ? Number(latest.values.LIABILITY ?? "0") : 0;

  return (
    <GlassCard>
      <div className="mb-1 text-sm text-text-muted">{t("classMix.title")}</div>
      {slices.length === 0 ? (
        <p className="py-10 text-center text-sm text-text-muted">
          {t("common:status.empty")}
        </p>
      ) : (
        <DonutChart
          data={slices}
          height={180}
          formatValue={(n) => formatCurrency(n, i18n.language)}
        >
          <div className="tnum text-lg font-[650] tracking-tight">
            {formatCurrency(total, i18n.language)}
          </div>
        </DonutChart>
      )}
      {liability < 0 && (
        <div className="mt-2 text-center text-xs text-negative">
          {formatCurrency(liability, i18n.language)} {t("classMix.liabilities")}
        </div>
      )}
    </GlassCard>
  );
}
