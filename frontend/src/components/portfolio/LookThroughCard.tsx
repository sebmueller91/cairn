import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { GlassCard } from "../ui/GlassCard";
import { Skeleton } from "../ui/Skeleton";
import { EmptyState } from "../ui/EmptyState";
import { HBarList, type HBarItem } from "../charts/HBarList";
import { api, type LookThroughResponse } from "../../lib/api";
import { formatCurrency, formatNumber, formatPercent } from "../../lib/format";
import { useIsLoading } from "../../lib/queryState";

function useLookThrough(dimension: "region" | "sector") {
  return useQuery({
    queryKey: ["look-through", dimension],
    queryFn: () => api.get<LookThroughResponse>(`/api/look-through?dimension=${dimension}`),
  });
}

function LookThroughColumn({ dimension }: { dimension: "region" | "sector" }) {
  const { t, i18n } = useTranslation(["portfolio", "common"]);
  const { data, isPending, isError } = useLookThrough(dimension);
  const pending = useIsLoading(isPending);

  const rows = (data?.rows ?? []).slice().sort(
    (a, b) => Number(b.value_eur) - Number(a.value_eur),
  );
  // Share of the look-through total, not of net worth: the question this
  // card answers is "how is what I hold in markets split up", so the
  // house and the mortgage have no business in the denominator.
  const total = rows.reduce((sum, row) => sum + Number(row.value_eur), 0);

  const items: HBarItem[] = rows.map((row) => {
    const share = total > 0 ? Number(row.value_eur) / total : 0;
    const benchmark = row.benchmark_pct == null ? null : Number(row.benchmark_pct) / 100;
    // Over- and underweight are choices, not mistakes — so the drift is
    // stated in percentage points and left in the muted colour rather
    // than being painted green/red like a gain.
    const driftPp = benchmark == null ? null : (share - benchmark) * 100;

    return {
      key: row.category,
      label: row.category,
      value: Number(row.value_eur),
      secondary: total > 0 && (
        <span className="flex items-baseline gap-2">
          <span className="tnum">{formatPercent(share, i18n.language)}</span>
          {driftPp != null && (
            <span className="tnum text-xs text-text-muted" title={t("lookThrough.benchmarkTooltip")}>
              {driftPp >= 0 ? "+" : "−"}
              {formatNumber(Math.abs(driftPp), i18n.language, {
                minimumFractionDigits: 1,
                maximumFractionDigits: 1,
              })}
              {" pp"}
            </span>
          )}
        </span>
      ),
    };
  });

  return (
    <div>
      <h3 className="mb-3 text-sm font-medium text-text-muted">
        {t(`lookThrough.${dimension}`)}
        {data?.benchmark_label && (
          <span className="ml-2 font-normal text-xs">
            {t("lookThrough.vsBenchmark", { benchmark: data.benchmark_label })}
          </span>
        )}
      </h3>
      {pending ? (
        <div className="space-y-3">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-full" />
        </div>
      ) : isError ? (
        <p className="text-sm text-text-muted">{t("common:status.error")}</p>
      ) : items.length === 0 ? (
        <EmptyState
          title={t("common:status.empty")}
          hint={t("lookThrough.emptyHint")}
          className="py-6"
        />
      ) : (
        <HBarList items={items} formatValue={(n) => formatCurrency(n, i18n.language)} />
      )}
    </div>
  );
}

/** Section 3 — ETF/stock look-through: value by region and by sector. */
export function LookThroughCard() {
  const { t } = useTranslation("portfolio");

  return (
    <GlassCard>
      <h2 className="font-medium">{t("lookThrough.title")}</h2>
      <p className="mt-1 text-xs text-text-muted">{t("lookThrough.caption")}</p>
      <div className="mt-4 grid grid-cols-1 gap-6 md:grid-cols-2">
        <LookThroughColumn dimension="region" />
        <LookThroughColumn dimension="sector" />
      </div>
    </GlassCard>
  );
}
