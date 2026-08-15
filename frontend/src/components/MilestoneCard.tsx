import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { api, type MilestoneResponse } from "../lib/api";
import { formatCurrency, formatDate } from "../lib/format";
import { Card } from "./Card";

export function MilestoneCard() {
  const { t, i18n } = useTranslation(["dashboard", "common"]);
  const { data } = useQuery({
    queryKey: ["milestones"],
    queryFn: () => api.get<MilestoneResponse>("/api/milestones?scope=net"),
  });

  if (!data) return null;

  return (
    <Card>
      <h2 className="mb-2 font-medium">{t("milestone.title")}</h2>
      <div className="tnum text-2xl font-semibold">
        {formatCurrency(data.next_milestone_eur, i18n.language)}
      </div>
      {data.months_to_reach != null && data.estimated_date ? (
        <p className="mt-1 text-sm text-text-muted">
          {t("milestone.eta", {
            date: formatDate(data.estimated_date, i18n.language),
            months: Math.round(data.months_to_reach),
          })}
        </p>
      ) : (
        <p className="mt-1 text-sm text-text-muted">{t("milestone.unreachable")}</p>
      )}
      <p className="mt-2 text-xs text-text-muted">
        {t("milestone.assumptions", {
          savings: formatCurrency(data.monthly_savings_eur, i18n.language),
          returnPct: data.assumed_annual_return_pct,
        })}
      </p>
    </Card>
  );
}
