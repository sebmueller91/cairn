import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { keepPreviousData } from "@tanstack/react-query";
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
/** Same reasoning as the tax view's own debounce: these two fields sit in
 * the query key, so raw keystrokes meant a request per digit — and "2" on
 * the way to "2285" is a projection nobody asked to see. */
const INPUT_DEBOUNCE_MS = 400;

/** The value, once the typing has stopped. Deliberately not the validating
 * hook TaxTab has: there the field is a German decimal that must parse
 * before it can be sent, here `type="number"` already narrows what can be
 * typed and an empty string is itself a meaningful state ("no override").
 * Kept local until a third caller wants it. */
function useDebouncedValue<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return settled;
}

/**
 * Where the wealth curve goes if nothing changes.
 *
 * This is the only card in the app whose numbers are not derived from a
 * recorded fact, and it is built to keep saying so without a disclaimer
 * to read: the assumptions sit in the card as editable controls rather
 * than in a footnote, the projection is drawn as a dashed line inside a
 * band rather than as a curve, and the savings rate says whether it was
 * measured or typed in.
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

  // The inputs render from the raw state (so typing stays responsive) but
  // the query reads these, so the chart re-fetches once per pause rather
  // than once per digit.
  const queriedReturnPct = useDebouncedValue(returnPct, INPUT_DEBOUNCE_MS);
  const queriedSavings = useDebouncedValue(savingsOverride, INPUT_DEBOUNCE_MS);

  const { data, isPending, isError } = useCachedQuery({
    queryKey: ["projection", years, real, queriedReturnPct, queriedSavings],
    queryFn: () => {
      const params = new URLSearchParams({
        scope: "net",
        years: String(years),
        annual_return_pct: queriedReturnPct,
        return_spread_pp: String(SPREAD_PP),
        real: String(real),
      });
      // Empty string means "no override" — but "0" is a real answer to
      // "what if I stopped saving", so it must not be swallowed by a
      // falsiness check here any more than by one on the server.
      if (queriedSavings !== "") params.set("monthly_savings_eur", queriedSavings);
      return api.get<ProjectionResponse>(`/api/projection?${params}`);
    },
    enabled: allSelected,
    // The horizon, the mode and both assumption fields are all in the key,
    // so every change used to drop `data` and swap the chart for a
    // skeleton — the card changed height under the cursor mid-edit. Hold
    // the last cone until the new one lands; it is a projection, and the
    // difference between the two is the point being looked at anyway.
    placeholderData: keepPreviousData,
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

  return (
    <GlassCard>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-medium">{t("outlook.title")}</h2>
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
