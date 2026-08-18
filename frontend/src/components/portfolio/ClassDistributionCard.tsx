import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { GlassCard } from "../ui/GlassCard";
import { Skeleton } from "../ui/Skeleton";
import { EmptyState } from "../ui/EmptyState";
import { DonutChart, type DonutSlice } from "../charts/DonutChart";
import { getAllocationTimeseries } from "../../lib/api";
import { formatCurrency, formatPercent } from "../../lib/format";
import { ASSET_CLASSES, ASSET_CLASS_COLORS, assetClassLabelKey } from "../../lib/assetClasses";
import { useAssetFilter } from "../../lib/assetFilter";

/** Section 1 — today's allocation by asset class, as a donut + legend. */
export function ClassDistributionCard() {
  const { t, i18n } = useTranslation(["portfolio", "common"]);
  const { selected } = useAssetFilter();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["allocation-timeseries", "latest"],
    queryFn: () => getAllocationTimeseries({}),
  });

  const latest = data && data.length > 0 ? data[data.length - 1] : null;

  const selectedClasses = ASSET_CLASSES.filter((c) => selected.has(c));
  const liabilitySelected = selectedClasses.includes("LIABILITY");
  const donutClasses = selectedClasses.filter((c) => c !== "LIABILITY");

  const rawValues = new Map(
    donutClasses.map((c) => [c, Number(latest?.values[c] ?? "0")]),
  );
  const slices: DonutSlice[] = donutClasses
    .filter((c) => (rawValues.get(c) ?? 0) > 0)
    .map((c) => ({
      name: t(`common:${assetClassLabelKey(c)}`),
      value: rawValues.get(c) ?? 0,
      color: ASSET_CLASS_COLORS[c],
    }));
  const positiveTotal = slices.reduce((sum, s) => sum + s.value, 0);
  const liabilityValue = Number(latest?.values.LIABILITY ?? "0");
  const netTotal = positiveTotal + (liabilitySelected ? liabilityValue : 0);

  return (
    <GlassCard glow>
      <h2 className="mb-4 font-medium">{t("classDistribution.title")}</h2>
      {isLoading ? (
        <div className="space-y-4">
          <Skeleton className="mx-auto h-60 w-60 rounded-full" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-full" />
        </div>
      ) : isError ? (
        <p className="text-sm text-text-muted">{t("common:status.error")}</p>
      ) : slices.length === 0 && !liabilitySelected ? (
        <EmptyState title={t("common:status.empty")} />
      ) : (
        <>
          {slices.length > 0 && (
            <DonutChart data={slices} formatValue={(n) => formatCurrency(n, i18n.language)}>
              <div className="tnum text-xl font-[650] tracking-tight">
                {formatCurrency(netTotal, i18n.language)}
              </div>
              <div className="mt-0.5 text-xs text-text-muted">
                {t("classDistribution.netLabel")}
              </div>
            </DonutChart>
          )}

          <div className="mt-4 space-y-2">
            {slices
              .slice()
              .sort((a, b) => b.value - a.value)
              .map((slice) => (
                <div key={slice.name} className="flex items-center gap-2 text-sm">
                  <span
                    aria-hidden
                    className="size-2 shrink-0 rounded-full"
                    style={{ backgroundColor: slice.color }}
                  />
                  <span className="truncate">{slice.name}</span>
                  <span className="tnum ml-auto shrink-0 font-medium">
                    {formatCurrency(slice.value, i18n.language)}
                  </span>
                  <span className="tnum w-14 shrink-0 text-right text-text-muted">
                    {positiveTotal > 0
                      ? formatPercent(slice.value / positiveTotal, i18n.language)
                      : "—"}
                  </span>
                </div>
              ))}

            {liabilitySelected && liabilityValue !== 0 && (
              <div className="flex items-center gap-2 text-sm">
                <span
                  aria-hidden
                  className="size-2 shrink-0 rounded-full"
                  style={{ backgroundColor: ASSET_CLASS_COLORS.LIABILITY }}
                />
                <span className="truncate">
                  {t(`common:${assetClassLabelKey("LIABILITY")}`)}
                </span>
                <span className="tnum ml-auto shrink-0 font-medium text-negative">
                  {formatCurrency(liabilityValue, i18n.language)}
                </span>
              </div>
            )}
          </div>
        </>
      )}
    </GlassCard>
  );
}
