import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { api, type AttributionResponse } from "../../lib/api";
import { formatCurrency } from "../../lib/format";
import { GlassCard } from "../ui/GlassCard";
import { Skeleton } from "../ui/Skeleton";
import { isoDaysAgo } from "./utils";

const ROWS = ["marketGains", "deposits", "income"] as const;

/** The most recent monthly attribution period, as three compact signed
 * rows. `from` trims the request to a couple of months of history — we
 * only ever read the last bucket. */
export function ThisMonthCard() {
  const { t, i18n } = useTranslation("overview");

  const { data, isLoading, isError } = useQuery({
    queryKey: ["attribution", "overview"],
    queryFn: () => {
      const params = new URLSearchParams({ granularity: "month", from: isoDaysAgo(60) });
      return api.get<AttributionResponse>(`/api/attribution?${params}`);
    },
  });

  if (isLoading) {
    return (
      <GlassCard className="space-y-3">
        <Skeleton className="h-4 w-28" />
        <Skeleton className="h-5 w-full" />
        <Skeleton className="h-5 w-full" />
        <Skeleton className="h-5 w-full" />
      </GlassCard>
    );
  }

  if (isError) {
    return (
      <GlassCard>
        <div className="mb-2 text-sm text-text-muted">{t("thisMonth.title")}</div>
        <p className="text-sm text-text-muted">{t("common:status.error")}</p>
      </GlassCard>
    );
  }

  const periods = data?.periods ?? [];
  const period = periods[periods.length - 1];

  if (!period) {
    return (
      <GlassCard>
        <div className="mb-2 text-sm text-text-muted">{t("thisMonth.title")}</div>
        <p className="text-sm text-text-muted">{t("common:status.empty")}</p>
      </GlassCard>
    );
  }

  const values: Record<(typeof ROWS)[number], number> = {
    marketGains: Number(period.market_gains_losses),
    deposits: Number(period.deposits_withdrawals),
    income: Number(period.income),
  };

  return (
    <GlassCard>
      <div className="mb-3 text-sm text-text-muted">{t("thisMonth.title")}</div>
      <div className="space-y-2.5">
        {ROWS.map((key) => {
          const value = values[key];
          return (
            <div key={key} className="flex items-center justify-between text-sm">
              <span className="text-text-muted">{t(`thisMonth.${key}`)}</span>
              <span
                className={`tnum font-medium ${
                  value > 0 ? "text-positive" : value < 0 ? "text-negative" : "text-text"
                }`}
              >
                {value >= 0 ? "+" : ""}
                {formatCurrency(value, i18n.language)}
              </span>
            </div>
          );
        })}
      </div>
    </GlassCard>
  );
}
