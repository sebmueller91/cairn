import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { GlassCard } from "../ui/GlassCard";
import { Skeleton } from "../ui/Skeleton";
import { EmptyState } from "../ui/EmptyState";
import { HBarList, type HBarItem } from "../charts/HBarList";
import { api, type LookThroughResponse } from "../../lib/api";
import { formatCurrency } from "../../lib/format";

function useLookThrough(dimension: "region" | "sector") {
  return useQuery({
    queryKey: ["look-through", dimension],
    queryFn: () => api.get<LookThroughResponse>(`/api/look-through?dimension=${dimension}`),
  });
}

function LookThroughColumn({ dimension }: { dimension: "region" | "sector" }) {
  const { t, i18n } = useTranslation(["portfolio", "common"]);
  const { data, isLoading, isError } = useLookThrough(dimension);

  const items: HBarItem[] = (data?.rows ?? [])
    .slice()
    .sort((a, b) => Number(b.value_eur) - Number(a.value_eur))
    .map((row) => ({ key: row.category, label: row.category, value: Number(row.value_eur) }));

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
