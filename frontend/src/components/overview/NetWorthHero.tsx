import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { formatCurrency } from "../../lib/format";
import { GlassCard } from "../ui/GlassCard";
import { StatHero } from "../ui/StatHero";
import { Sparkline } from "../ui/Sparkline";
import { Skeleton } from "../ui/Skeleton";
import { closestPoint, fetchNetWorth90d, NET_WORTH_QUERY_KEY } from "./utils";

/** The hero panel: latest net worth (scope=net, so loans count against it),
 * a 90-day sparkline, and a delta chip vs. ~30 days ago. Single query — the
 * sparkline and the delta both read off the same 90-day series. */
export function NetWorthHero() {
  const { t, i18n } = useTranslation("overview");

  const { data, isLoading, isError } = useQuery({
    queryKey: NET_WORTH_QUERY_KEY,
    queryFn: fetchNetWorth90d,
  });

  if (isLoading) {
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
  target.setDate(target.getDate() - 30);
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
      >
        <Sparkline
          data={points.map((p) => Number(p.value_eur))}
          width={640}
          height={56}
          className="w-full"
        />
      </StatHero>
    </GlassCard>
  );
}
