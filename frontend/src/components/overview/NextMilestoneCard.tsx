import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { api, type MilestoneResponse } from "../../lib/api";
import { formatCurrency, formatDate } from "../../lib/format";
import { GlassCard } from "../ui/GlassCard";
import { ProgressArc } from "../ui/ProgressArc";
import { Skeleton } from "../ui/Skeleton";

/** Progress toward the next round-number milestone (scope=net). */
export function NextMilestoneCard() {
  const { t, i18n } = useTranslation("overview");

  const { data, isLoading, isError } = useQuery({
    queryKey: ["milestones", "overview"],
    queryFn: () => api.get<MilestoneResponse>("/api/milestones?scope=net"),
  });

  if (isLoading) {
    return (
      <GlassCard className="flex flex-col items-center">
        <Skeleton className="h-4 w-32 self-start" />
        <Skeleton className="mt-6 size-32 rounded-full" />
        <Skeleton className="mt-4 h-3 w-36" />
      </GlassCard>
    );
  }

  if (isError || !data) {
    return (
      <GlassCard>
        <div className="mb-2 text-sm text-text-muted">{t("milestone.title")}</div>
        <p className="text-sm text-text-muted">{t("common:status.error")}</p>
      </GlassCard>
    );
  }

  const current = Number(data.current_value_eur);
  const target = Number(data.next_milestone_eur);
  const pct = target > 0 ? (current / target) * 100 : 0;

  return (
    <GlassCard className="flex flex-col items-center text-center">
      <div className="mb-4 self-start text-sm text-text-muted">{t("milestone.title")}</div>
      <ProgressArc
        pct={pct}
        size={128}
        label={formatCurrency(data.next_milestone_eur, i18n.language)}
        sublabel={data.estimated_date ? formatDate(data.estimated_date, i18n.language) : "—"}
      />
      <p className="mt-4 text-xs text-text-muted">
        {data.months_to_reach != null
          ? t("milestone.caption", { months: Math.round(data.months_to_reach) })
          : t("milestone.unreachable")}
      </p>
    </GlassCard>
  );
}
