import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { GlassCard } from "../ui/GlassCard";
import { Skeleton } from "../ui/Skeleton";
import { EmptyState } from "../ui/EmptyState";
import { HBarList, type HBarItem } from "../charts/HBarList";
import { api, type LookThroughResponse } from "../../lib/api";
import { formatCurrency, formatPercent } from "../../lib/format";

function useLookThrough(dimension: "region" | "sector") {
  return useQuery({
    queryKey: ["look-through", dimension],
    queryFn: () => api.get<LookThroughResponse>(`/api/look-through?dimension=${dimension}`),
  });
}

function LookThroughColumn({ dimension }: { dimension: "region" | "sector" }) {
  const { t, i18n } = useTranslation(["portfolio", "common"]);
  const { data, isLoading, isError } = useLookThrough(dimension);

  const rows = (data?.rows ?? []).slice().sort(
    (a, b) => Number(b.value_eur) - Number(a.value_eur),
  );
  // Share of the look-through total, not of net worth: the question this
  // card answers is "how is what I hold in markets split up", so the
  // house and the mortgage have no business in the denominator.
  const total = rows.reduce((sum, row) => sum + Number(row.value_eur), 0);

  const items: HBarItem[] = rows.map((row) => ({
    key: row.category,
    label: row.category,
    value: Number(row.value_eur),
    secondary: total > 0 && (
      <span className="tnum text-text-muted">
        {formatPercent(Number(row.value_eur) / total, i18n.language)}
      </span>
    ),
  }));

  return (
    <div>
      <h3 className="mb-3 text-sm font-medium text-text-muted">
        {t(`lookThrough.${dimension}`)}
      </h3>
      {isLoading ? (
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
