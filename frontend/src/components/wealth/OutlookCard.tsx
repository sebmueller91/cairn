import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Telescope } from "lucide-react";
import { api, type AllocationTimeseriesPoint, type ProjectionResponse } from "../../lib/api";
import { sumSelected } from "../../lib/allocationSeries";
import type { AssetClass } from "../../lib/assetClasses";
import { formatCurrency, formatNumber } from "../../lib/format";
import { ProjectionConeChart, type ConePoint } from "../charts/ProjectionConeChart";
import { EmptyState } from "../ui/EmptyState";
import { GlassCard } from "../ui/GlassCard";
import { SegmentedControl } from "../ui/SegmentedControl";
import { Skeleton } from "../ui/Skeleton";
import { useCachedQuery, useIsLoading } from "../../lib/queryState";

const HORIZONS = [5, 10, 20, 30] as const;
/** Rendered as a range around the central assumption, e.g. 3 % – 7 %. */
const SPREAD_PP = 2;
/** How much recorded history to show alongside, so the seam has context. */
const HISTORY_MONTHS = 36;

/**
 * Where the wealth curve goes if nothing changes.
 *
 * This is the only card in the app whose numbers are not derived from a
 * recorded fact, and it is built to keep saying so: the assumptions sit
 * in the header as controls rather than in a footnote, the projection is
 * drawn as a dashed line inside a band rather than as a curve, and the
 * savings rate says whether it was measured or typed in.
 *
 * Whole-portfolio only. The starting value is the net-worth snapshot and
 * the savings rate is a portfolio-wide flow, so projecting "just the
 * equities" would compound a number against a rate that never belonged
 * to it — the same reason the curve card disables real terms under a
 * narrowed filter and the milestone card only trusts the server estimate
 * when the filter is off.
 *
 * The nominal/real toggle is this card's own rather than the page's. The
 * curve's real mode is measured CPI deflation and switches itself off
 * when no CPI is loaded; this one deflates by an *assumed* forward rate
 * and needs no CPI at all. Sharing one control would either disable this
 * for no reason or silently show two different bases under one label.
 */
export function OutlookCard({
  history,
  selected,
  allSelected,
  isLoading,
}: {
  /** Full history at month granularity — the same query the milestone ladder uses. */
  history: AllocationTimeseriesPoint[] | undefined;
  selected: Set<AssetClass>;
  allSelected: boolean;
  isLoading: boolean;
}) {
  const { t, i18n } = useTranslation(["wealth", "common"]);
  const [years, setYears] = useState<number>(10);
  const [real, setReal] = useState(false);
  const [returnPct, setReturnPct] = useState("5");
  const [savingsOverride, setSavingsOverride] = useState<string>("");

  const { data, isPending, isError } = useCachedQuery({
    queryKey: ["projection", years, real, returnPct, savingsOverride],
    queryFn: () => {
      const params = new URLSearchParams({
        scope: "net",
        years: String(years),
        annual_return_pct: returnPct,
        return_spread_pp: String(SPREAD_PP),
        real: String(real),
      });
      // Empty string means "no override" — but "0" is a real answer to
      // "what if I stopped saving", so it must not be swallowed by a
      // falsiness check here any more than by one on the server.
      if (savingsOverride !== "") params.set("monthly_savings_eur", savingsOverride);
      return api.get<ProjectionResponse>(`/api/projection?${params}`);
    },
    enabled: allSelected,
  });
  const pending = useIsLoading(isPending) && allSelected;

  const historyTail = useMemo(() => {
    const series = sumSelected(history ?? [], selected);
    return series.slice(-HISTORY_MONTHS);
  }, [history, selected]);

  const cone: ConePoint[] = useMemo(
    () =>
      (data?.points ?? []).map((p) => ({
        date: p.date,
        low: Number(p.low_eur),
        mid: Number(p.mid_eur),
        high: Number(p.high_eur),
      })),
    [data],
  );

  const formatValue = (n: number) => formatCurrency(n, i18n.language);
  const last = cone.at(-1);

  return (
    <GlassCard>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-medium">{t("outlook.title")}</h2>
          <p className="mt-1 text-xs text-text-muted">{t("outlook.disclaimer")}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <SegmentedControl
            options={HORIZONS.map((y) => ({
              value: String(y),
              label: t("outlook.years", { count: y }),
            }))}
            value={String(years)}
            onChange={(v) => setYears(Number(v))}
          />
          <SegmentedControl
            options={[
              { value: "nominal", label: t("mode.nominal") },
              { value: "real", label: t("mode.real") },
            ]}
            value={real ? "real" : "nominal"}
            onChange={(v) => setReal(v === "real")}
          />
        </div>
      </div>

      {!allSelected ? (
        <EmptyState
          icon={<Telescope className="size-8" aria-hidden />}
          title={t("outlook.filteredTitle")}
          hint={t("outlook.filteredHint")}
        />
      ) : pending || isLoading ? (
        <div className="mt-5 space-y-4">
          <Skeleton className="h-4 w-40" />
          <Skeleton className="h-[300px] w-full" />
        </div>
      ) : isError ? (
        <p className="mt-4 text-sm text-text-muted">{t("common:status.error")}</p>
      ) : cone.length === 0 ? (
        <EmptyState
          icon={<Telescope className="size-8" aria-hidden />}
          title={t("outlook.emptyTitle")}
          hint={t("outlook.emptyHint")}
        />
      ) : (
        <>
          <div className="mt-4">
            <ProjectionConeChart
              history={historyTail}
              cone={cone}
              seamDate={data!.start_date}
              seamLabel={t("outlook.today")}
              historyLabel={t("outlook.recorded")}
              projectionLabel={t("outlook.projected")}
              rangeLabel={t("outlook.range")}
              formatValue={formatValue}
            />
          </div>

          {last && (
            <p className="mt-4 text-sm">
              {t("outlook.summary", {
                years,
                value: formatCurrency(last.mid, i18n.language),
              })}{" "}
              <span className="text-text-muted">
                {t("outlook.summaryRange", {
                  low: formatCurrency(last.low, i18n.language),
                  high: formatCurrency(last.high, i18n.language),
                })}
              </span>
            </p>
          )}

          {/* The assumptions, editable in place. A projection whose
              premises are buried is unreadable — the same curve means
              entirely different things at 3 % and at 8 %. */}
          <div className="mt-4 flex flex-wrap items-end gap-x-6 gap-y-3 border-t border-border pt-4 text-xs">
            <label className="flex flex-col gap-1">
              <span className="text-text-muted">{t("outlook.assumedReturn")}</span>
              <span className="flex items-center gap-1.5">
                <input
                  type="number"
                  step="0.5"
                  min="-20"
                  max="20"
                  value={returnPct}
                  onChange={(e) => setReturnPct(e.target.value)}
                  className="h-8 w-20 rounded-lg border border-border bg-bg-subtle px-2 text-xs tnum text-text focus:outline-none focus:ring-1 focus:ring-accent"
                />
                <span className="text-text-muted">
                  {t("outlook.spread", {
                    low: formatNumber(Number(returnPct) - SPREAD_PP, i18n.language, {
                      maximumFractionDigits: 1,
                    }),
                    high: formatNumber(Number(returnPct) + SPREAD_PP, i18n.language, {
                      maximumFractionDigits: 1,
                    }),
                  })}
                </span>
              </span>
            </label>

            <label className="flex flex-col gap-1">
              <span className="text-text-muted">{t("outlook.monthlySavings")}</span>
              <span className="flex items-center gap-1.5">
                <input
                  type="number"
                  step="50"
                  value={savingsOverride}
                  placeholder={
                    data ? formatNumber(Number(data.monthly_savings_eur), i18n.language, {
                      maximumFractionDigits: 0,
                    }) : ""
                  }
                  onChange={(e) => setSavingsOverride(e.target.value)}
                  className="h-8 w-24 rounded-lg border border-border bg-bg-subtle px-2 text-xs tnum text-text focus:outline-none focus:ring-1 focus:ring-accent"
                />
                {/* Measured and typed-in must never look the same. */}
                <span className="text-text-muted">
                  {data?.monthly_savings_source === "override"
                    ? t("outlook.savingsOverride")
                    : t("outlook.savingsDerived")}
                </span>
                {savingsOverride !== "" && (
                  <button
                    type="button"
                    onClick={() => setSavingsOverride("")}
                    className="font-medium text-accent hover:underline"
                  >
                    {t("outlook.reset")}
                  </button>
                )}
              </span>
            </label>

            {real && data && (
              <span className="text-text-muted">
                {t("outlook.inflationNote", {
                  pct: formatNumber(Number(data.annual_inflation_pct), i18n.language, {
                    maximumFractionDigits: 1,
                  }),
                })}
              </span>
            )}
          </div>
        </>
      )}
    </GlassCard>
  );
}
