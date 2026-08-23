import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { getContributions } from "../../lib/api";
import { formatCurrency } from "../../lib/format";
import { ASSET_CLASSES, ASSET_CLASS_COLORS, assetClassLabelKey } from "../../lib/assetClasses";
import type { AssetClass } from "../../lib/assetClasses";
import { GlassCard } from "../ui/GlassCard";
import { Skeleton } from "../ui/Skeleton";
import { ChartLegend, type LegendItem } from "../charts/ChartLegend";
import { useIsLoading } from "../../lib/queryState";

/**
 * What actually went in over the trailing year: money invested per asset
 * class, principal repaid, and how far net worth moved.
 *
 * Replaces the old single-month attribution card. A month of market noise
 * says little about whether the year went well; contributions and debt
 * repayment are the two things that are actually a decision rather than a
 * price move, and a year is the shortest window where they read clearly.
 *
 * The three figures deliberately do not reconcile with each other — money
 * invested plus debt repaid is not the change in net worth, because markets
 * moved in between. Attribution (Performance page) is the view that closes
 * that gap.
 */
export function LastTwelveMonthsCard() {
  const { t, i18n } = useTranslation("overview");

  const { data, isPending, isError } = useQuery({
    queryKey: ["contributions", "overview-12m"],
    queryFn: () => getContributions(),
  });
  const pending = useIsLoading(isPending);

  if (pending) {
    return (
      <GlassCard className="space-y-3">
        <Skeleton className="h-4 w-32" />
        <Skeleton className="h-7 w-40" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-full" />
      </GlassCard>
    );
  }

  if (isError || !data) {
    return (
      <GlassCard>
        <div className="mb-2 text-sm text-text-muted">{t("lastYear.title")}</div>
        <p className="text-sm text-text-muted">{t("common:status.error")}</p>
      </GlassCard>
    );
  }

  const invested = Number(data.total_invested);
  const debtRepaid = Number(data.debt_repaid);
  const netChange = Number(data.net_worth_change);

  // ASSET_CLASSES order, not API order, so the colours and the sequence match
  // the donut in the neighbouring card. Negative nets (a class sold down
  // overall) are kept — they belong in a "what did I put in" figure.
  const rows: LegendItem[] = ASSET_CLASSES.filter(
    (c: AssetClass) => c !== "LIABILITY" && data.by_asset_class[c] !== undefined,
  ).map((c: AssetClass) => ({
    key: c,
    label: t(`common:${assetClassLabelKey(c)}`),
    color: ASSET_CLASS_COLORS[c],
    value: Number(data.by_asset_class[c]),
  }));

  const money = (n: number) => formatCurrency(n, i18n.language);
  const signed = (n: number) => `${n >= 0 ? "+" : ""}${money(n)}`;

  return (
    <GlassCard>
      <div className="text-sm text-text-muted">{t("lastYear.title")}</div>
      <div className="mt-1 text-xs text-text-muted">
        {t("lastYear.range", {
          from: new Date(data.start_date).toLocaleDateString(
            i18n.language === "de" ? "de-DE" : "en-GB",
            { month: "short", year: "numeric" },
          ),
        })}
      </div>

      <div className="mt-3">
        <div className="tnum sensitive text-lg font-[650] leading-tight tracking-tight">
          {money(invested)}
        </div>
        <div className="text-xs text-text-muted">{t("lastYear.invested")}</div>
      </div>

      {rows.length > 0 ? (
        <ChartLegend
          items={rows}
          language={i18n.language}
          formatValue={money}
          className="mt-2.5"
        />
      ) : (
        <p className="mt-2 text-xs text-text-muted">{t("lastYear.noContributions")}</p>
      )}

      <dl className="mt-3 space-y-1.5 border-t border-border pt-2.5 text-sm">
        <div className="flex items-center justify-between gap-2">
          <dt className="text-text-muted">{t("lastYear.debtRepaid")}</dt>
          <dd className={`tnum sensitive font-medium ${debtRepaid > 0 ? "text-positive" : ""}`}>
            {money(debtRepaid)}
          </dd>
        </div>
        <div className="flex items-center justify-between gap-2">
          <dt className="text-text-muted">{t("lastYear.netChange")}</dt>
          <dd
            className={`tnum sensitive font-medium ${
              netChange > 0 ? "text-positive" : netChange < 0 ? "text-negative" : ""
            }`}
          >
            {signed(netChange)}
          </dd>
        </div>
      </dl>
    </GlassCard>
  );
}
