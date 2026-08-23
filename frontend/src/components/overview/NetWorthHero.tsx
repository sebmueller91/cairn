import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { formatCurrency } from "../../lib/format";
import { GlassCard } from "../ui/GlassCard";
import { StatHero } from "../ui/StatHero";
import { Sparkline } from "../ui/Sparkline";
import { Skeleton } from "../ui/Skeleton";
import { closestPoint, fetchHeroNetWorth, HERO_DAYS, netWorthQueryKey } from "./utils";
import { useIsLoading } from "../../lib/queryState";

/** The hero panel: latest net worth (scope=net, so loans count against it),
 * a sparkline over HERO_DAYS, and a delta chip against the start of that
 * same window. Single query — sparkline and delta read off one series, and
 * one constant, so the curve and the number always cover the same period. */
export function NetWorthHero() {
  const { t, i18n } = useTranslation("overview");

  const { data, isPending, isError } = useQuery({
    queryKey: netWorthQueryKey(),
    queryFn: fetchHeroNetWorth,
  });

  // The IndexedDB cache restore forces every query into fetchStatus "idle",
  // so isPending alone would read as "done, no data" during that window —
  // isRestoring closes that gap so we skeleton instead of rendering `null`
  // or (worse) the empty-page fallback in Overview.tsx.
  const pending = useIsLoading(isPending);

  if (pending) {
    return (
      <GlassCard glow className="md:p-6">
        <Skeleton className="h-4 w-32" />
        <Skeleton className="mt-3 h-11 w-64" />
        <Skeleton className="mt-4 h-14 w-full" />
      </GlassCard>
    );
  }

  if (isError) {
    return (
      <GlassCard glow className="md:p-6">
        <div className="text-sm text-text-muted">{t("hero.label")}</div>
        <p className="mt-2 text-sm text-text-muted">{t("common:status.error")}</p>
      </GlassCard>
    );
  }

  const points = data ?? [];
  // Nothing to show yet — the page-level EmptyState (Overview.tsx) covers
  // the "no snapshots at all" case, so this component just steps aside.
  if (points.length === 0) return null;

  const latest = points[points.length - 1];
  const latestValue = Number(latest.value_eur);

  const target = new Date();
  target.setDate(target.getDate() - HERO_DAYS);
  const reference = closestPoint(points, target);
  const delta = reference ? latestValue - Number(reference.value_eur) : undefined;

  const format = (n: number) => formatCurrency(n, i18n.language);
  const formatDelta = (n: number) => `${n >= 0 ? "+" : ""}${format(n)}`;

  return (
    <GlassCard glow className="md:p-6">
      <StatHero
        label={t("hero.label")}
        value={latestValue}
        format={format}
        delta={delta}
        formatDelta={formatDelta}
        sensitive
      >
        <Sparkline
          data={points.map((p) => Number(p.value_eur))}
          width={640}
          height={56}
          className="w-full"
        />
        <div className="mt-1.5 text-xs text-text-muted">
          {t("hero.sparkCaption", { days: HERO_DAYS })}
        </div>
      </StatHero>
    </GlassCard>
  );
}
