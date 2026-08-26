import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { Layers } from "lucide-react";
import {
  api,
  type AllocationBreakdownResponse,
  type ConcentrationResponse,
} from "../../lib/api";
import { formatCurrency, formatNumber, formatPercent } from "../../lib/format";
import { GlassCard } from "../ui/GlassCard";
import { HBarList, type HBarItem } from "../charts/HBarList";
import { SegmentedControl } from "../ui/SegmentedControl";
import { Skeleton } from "../ui/Skeleton";
import { EmptyState } from "../ui/EmptyState";
import { useIsLoading } from "../../lib/queryState";

type Dimension = "currency" | "liquidity" | "account";
const DIMENSIONS: Dimension[] = ["currency", "liquidity", "account"];

/** One headline figure with its explanation underneath. */
function Metric({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint: string;
}) {
  return (
    <div className="min-w-0">
      <div className="text-xs text-text-muted">{label}</div>
      <div className="tnum sensitive mt-0.5 text-xl font-[650] tracking-tight">{value}</div>
      <div className="mt-0.5 text-xs text-text-muted">{hint}</div>
    </div>
  );
}

/**
 * How lopsided the portfolio is, and what it is made of along the two
 * axes `instrument` records but nothing else aggregates.
 *
 * The mix cards above answer "how much equity"; two portfolios can give
 * the same answer while one holds forty funds and the other holds two.
 * These are the figures that separate them.
 */
export function ConcentrationCard() {
  const { t, i18n } = useTranslation(["portfolio", "common"]);
  const [dimension, setDimension] = useState<Dimension>("currency");

  const conc = useQuery({
    queryKey: ["concentration"],
    queryFn: () => api.get<ConcentrationResponse>("/api/concentration"),
  });
  const breakdown = useQuery({
    queryKey: ["allocationBreakdown", dimension],
    queryFn: () =>
      api.get<AllocationBreakdownResponse>(
        `/api/allocation/breakdown?dimension=${dimension}&scope=investable`,
      ),
  });
  const pending = useIsLoading(conc.isPending, breakdown.isPending);

  const bars: HBarItem[] = useMemo(() => {
    const buckets = breakdown.data?.buckets ?? [];
    const total = Number(breakdown.data?.total_eur ?? 0);
    return buckets
      .filter((b) => Number(b.value_eur) > 0)
      .map((b) => ({
        key: b.key || "unclassified",
        // An empty key means the dimension does not classify this row —
        // named as such rather than left blank, because "you have not
        // filled this in" is the actual finding.
        label: b.key === "" ? t("concentration.unclassified") : bucketLabel(b.key, b.label),
        value: Number(b.value_eur),
        color: b.key === "" ? "var(--text-muted)" : undefined,
        secondary:
          total > 0 ? (
            <span className="tnum text-xs text-text-muted">
              {formatPercent(Number(b.value_eur) / total, i18n.language)}
            </span>
          ) : undefined,
      }));
    function bucketLabel(key: string, label: string) {
      // Liquidity tiers are spec 2.2's T0–T3; the codes alone say nothing.
      if (dimension === "liquidity") return t(`concentration.tier.${key}`);
      return label;
    }
  }, [breakdown.data, dimension, t, i18n.language]);

  const c = conc.data;
  const nothing = c && c.hhi === null;

  // "Top 10" is a dead figure for a book of eight holdings — it reads
  // 100 % forever and says nothing. Fall back to a slice that still
  // divides the portfolio, and label whichever one is shown. Computed
  // from `holdings` (complete and already sorted) rather than by asking
  // the server again; its own top_n_share stays the canonical 10 for
  // anything reading the API directly.
  const shownTopN = c && c.holdings_count > 10 ? c.top_n : 3;
  const shownTopShare = c?.holdings.length
    ? c.holdings.slice(0, shownTopN).reduce((sum, h) => sum + h.share, 0)
    : null;

  return (
    <GlassCard>
      <h2 className="mb-1 font-medium">{t("concentration.title")}</h2>
      <p className="mb-4 text-xs text-text-muted">{t("concentration.subtitle")}</p>

      {pending ? (
        <div className="space-y-4">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-full" />
        </div>
      ) : conc.isError || breakdown.isError ? (
        <p className="text-sm text-text-muted">{t("common:status.error")}</p>
      ) : nothing || !c ? (
        <EmptyState
          icon={<Layers className="size-8" aria-hidden />}
          title={t("concentration.empty")}
        />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <Metric
              label={t("concentration.topN", { n: shownTopN })}
              value={shownTopShare === null ? "—" : formatPercent(shownTopShare, i18n.language)}
              hint={t("concentration.ofHoldings", { count: c.holdings_count })}
            />
            <Metric
              label={t("concentration.largest")}
              value={c.largest_share === null ? "—" : formatPercent(c.largest_share, i18n.language)}
              hint={c.holdings[0]?.name ?? ""}
            />
            <Metric
              label={t("concentration.hhi")}
              value={c.hhi === null ? "—" : formatNumber(c.hhi, i18n.language, { maximumFractionDigits: 0 })}
              hint={t("concentration.hhiHint")}
            />
            <Metric
              label={t("concentration.effective")}
              value={
                c.effective_holdings === null
                  ? "—"
                  : formatNumber(c.effective_holdings, i18n.language, {
                      maximumFractionDigits: 1,
                    })
              }
              hint={t("concentration.effectiveHint")}
            />
          </div>

          {/* Stated where the numbers are, not in a footnote: these count
              funds, not what is inside them, and the app has no
              constituent data to do otherwise. */}
          <p className="mt-3 text-xs text-text-muted">{t("concentration.lookThroughCaveat")}</p>

          <div className="mt-6 border-t border-border pt-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-medium">{t("concentration.structureTitle")}</h3>
              <SegmentedControl
                options={DIMENSIONS.map((d) => ({
                  value: d,
                  label: t(`concentration.dimension.${d}`),
                }))}
                value={dimension}
                onChange={(v) => setDimension(v as Dimension)}
              />
            </div>
            {bars.length === 0 ? (
              <EmptyState title={t("common:status.empty")} />
            ) : (
              <>
                <HBarList
                  items={bars}
                  formatValue={(n) => formatCurrency(n, i18n.language)}
                />
                {dimension === "liquidity" && (
                  <p className="mt-3 text-xs text-text-muted">
                    {t("concentration.liquidityHint")}
                  </p>
                )}
                {dimension === "currency" && (
                  <p className="mt-3 text-xs text-text-muted">
                    {t("concentration.currencyHint")}
                  </p>
                )}
              </>
            )}
          </div>
        </>
      )}
    </GlassCard>
  );
}
