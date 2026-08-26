import { useTranslation } from "react-i18next";
import { api, type MilestoneResponse } from "../../lib/api";
import { formatCurrency, formatDate, formatPercent } from "../../lib/format";
import { GlassCard } from "../ui/GlassCard";
import { ProgressArc } from "../ui/ProgressArc";
import { Skeleton } from "../ui/Skeleton";
import { useCachedQuery, useIsLoading } from "../../lib/queryState";

/** Progress toward the next round-number milestone (scope=net).
 *
 * The ring holds the percentage, not the target: a seven-figure euro amount
 * does not fit inside a 112px arc and used to spill over the stroke. The
 * target and the projected date sit beside it as ordinary text, where they
 * have room to be read. */
export function NextMilestoneCard() {
  const { t, i18n } = useTranslation("overview");

  const { data, isPending, isError } = useCachedQuery({
    queryKey: ["milestones", "overview"],
    queryFn: () => api.get<MilestoneResponse>("/api/milestones?scope=net"),
  });
  const pending = useIsLoading(isPending);

  if (pending) {
    return (
      <GlassCard>
        <Skeleton className="h-4 w-32" />
        <Skeleton className="mt-6 size-28 rounded-full" />
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
    <GlassCard>
      <div className="text-sm text-text-muted">{t("milestone.title")}</div>
      <div className="mt-3 flex items-center gap-4">
        <ProgressArc
          pct={pct}
          size={112}
          strokeWidth={9}
          label={formatPercent(pct / 100, i18n.language, { maximumFractionDigits: 0 })}
          className="shrink-0"
        />
        <div className="min-w-0 flex-1">
          <div className="tnum sensitive text-lg font-[650] leading-tight tracking-tight">
            {formatCurrency(data.next_milestone_eur, i18n.language)}
          </div>
          <div className="text-xs text-text-muted">{t("milestone.targetLabel")}</div>
          <div className="tnum mt-2 text-sm">
            {data.estimated_date ? formatDate(data.estimated_date, i18n.language) : "—"}
          </div>
          <div className="text-xs text-text-muted">
            {data.months_to_reach != null
              ? t("milestone.caption", { months: Math.round(data.months_to_reach) })
              : t("milestone.unreachable")}
          </div>
        </div>
      </div>
    </GlassCard>
  );
}
