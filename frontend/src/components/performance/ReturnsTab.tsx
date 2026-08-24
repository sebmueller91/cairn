import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { TrendingUp } from "lucide-react";
import { api, type Instrument, type PerformanceResponse } from "../../lib/api";
import { formatDate, formatNumber, formatPercent } from "../../lib/format";
import { GlassCard } from "../ui/GlassCard";
import { SegmentedControl } from "../ui/SegmentedControl";
import { StatHero } from "../ui/StatHero";
import { Skeleton } from "../ui/Skeleton";
import { EmptyState } from "../ui/EmptyState";
import { LineCompareChart } from "../charts/LineCompareChart";
import { useIsLoading } from "../../lib/queryState";
import { useAssetFilter } from "../../lib/assetFilter";
import { ASSET_CLASSES } from "../../lib/assetClasses";

type Period = "1M" | "3M" | "YTD" | "1Y" | "3Y" | "5Y" | "inception";
const PERIODS: Period[] = ["1M", "3M", "YTD", "1Y", "3Y", "5Y", "inception"];
type Method = "twr" | "mwr";

// Survives a reload — the benchmark is a preference, not view state.
const BENCHMARK_STORAGE_KEY = "cairn-benchmark";

export function ReturnsTab() {
  const { t, i18n } = useTranslation("performance");
  const { selected, allSelected } = useAssetFilter();
  // Built by walking ASSET_CLASSES rather than the Set, so an identical
  // selection always yields an identical string: a Set preserves
  // insertion order, so toggling a class off and back on would otherwise
  // move it to the end and produce a new query key for the same filter.
  const assetClassParam = allSelected
    ? null
    : ASSET_CLASSES.filter((c) => selected.has(c)).join(",");
  const [period, setPeriod] = useState<Period>("1Y");
  const [method, setMethod] = useState<Method>("twr");
  const [benchmarkId, setBenchmarkId] = useState<string>(
    () => localStorage.getItem(BENCHMARK_STORAGE_KEY) ?? "",
  );

  useEffect(() => {
    localStorage.setItem(BENCHMARK_STORAGE_KEY, benchmarkId);
  }, [benchmarkId]);

  const { data: instruments } = useQuery({
    queryKey: ["instruments"],
    queryFn: () => api.get<Instrument[]>("/api/instruments"),
  });
  const marketInstruments = (instruments ?? []).filter((i) => i.valuation_mode === "MARKET");
  const benchmarkName = instruments?.find((i) => String(i.id) === benchmarkId)?.name;

  // A benchmark instrument that gets deleted after being picked here stays
  // pinned in localStorage forever (BENCHMARK_STORAGE_KEY), so the curve
  // silently stops carrying `benchmark_curve` on every future reload with
  // no indication why. Once the instrument list has actually loaded, drop
  // a benchmark id that isn't in it. Guarded on `instruments` being present
  // (not merely "not pending") so a transient fetch failure can't be
  // mistaken for "the instrument is gone" and wipe a valid preference.
  useEffect(() => {
    if (!instruments) return;
    if (benchmarkId && !instruments.some((i) => String(i.id) === benchmarkId)) {
      setBenchmarkId("");
    }
  }, [instruments, benchmarkId]);

  const { data: perf, isPending, isError } = useQuery({
    queryKey: ["performance", period, method, benchmarkId, assetClassParam],
    queryFn: () => {
      const params = new URLSearchParams({ scope: "total", period, method });
      if (benchmarkId && method === "twr") params.set("benchmark_instrument_id", benchmarkId);
      if (assetClassParam) params.set("asset_classes", assetClassParam);
      return api.get<PerformanceResponse>(`/api/performance?${params}`);
    },
  });
  const pending = useIsLoading(isPending);

  const periodOptions = PERIODS.map((p) => ({ value: p, label: t(`periods.${p}`) }));
  const methodOptions = (["twr", "mwr"] as Method[]).map((m) => ({
    value: m,
    label: t(`methods.${m}`),
  }));

  const curveData = perf?.curve?.map((p) => ({ date: p.date, value: p.index_value })) ?? [];
  const benchmarkCurveData = perf?.benchmark_curve?.map((p) => ({ date: p.date, value: p.index_value }));

  // The comparison the benchmark exists to make, stated outright. Both
  // curves are indexed to 100 at the window start, so they always *look*
  // like they begin together — without these two figures there is no way
  // to read either total off the chart, and a benchmark that happens to
  // land near the portfolio is indistinguishable from one that never
  // loaded. Expressed in percentage points: it is a difference of two
  // percentages, not a percentage of one.
  const benchmarkReturn = benchmarkId && method === "twr" ? perf?.benchmark_return_pct : null;
  const excessPp =
    perf?.return_pct != null && benchmarkReturn != null
      ? (perf.return_pct - benchmarkReturn) * 100
      : null;

  return (
    <div className="space-y-6">
      <GlassCard className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
        <SegmentedControl options={periodOptions} value={period} onChange={setPeriod} />
        <div className="flex flex-wrap items-center gap-2">
          <SegmentedControl options={methodOptions} value={method} onChange={setMethod} />
          {method === "twr" && (
            <select
              value={benchmarkId}
              onChange={(e) => setBenchmarkId(e.target.value)}
              className="h-8 rounded-full border border-border bg-bg-subtle px-3 text-xs text-text focus:outline-none focus:ring-1 focus:ring-accent"
            >
              <option value="">{t("noBenchmark")}</option>
              {marketInstruments.map((i) => (
                <option key={i.id} value={i.id}>
                  {i.name}
                </option>
              ))}
            </select>
          )}
        </div>
      </GlassCard>

      {pending ? (
        <GlassCard>
          <Skeleton className="h-4 w-32" />
          <Skeleton className="mt-3 h-12 w-48" />
          <Skeleton className="mt-6 h-64 w-full" />
        </GlassCard>
      ) : isError ? (
        <GlassCard>
          <p className="text-sm text-text-muted">{t("common:status.error")}</p>
        </GlassCard>
      ) : !perf || (perf.return_pct == null && curveData.length === 0) ? (
        // Genuinely nothing for this window — not just "no return_pct".
        // The backend returns return_pct: None whenever the window has no
        // daily returns, but `curve` can still be populated (e.g. picking
        // 1M when the last nightly snapshot is older than a month) — that
        // used to hide the whole card instead of the one figure it lacks.
        <GlassCard>
          <EmptyState
            icon={<TrendingUp className="size-8" aria-hidden />}
            title={allSelected ? t("noData") : t("noDataForFilter")}
            hint={allSelected ? undefined : t("noDataForFilterHint")}
          />
        </GlassCard>
      ) : (
        <GlassCard
          className={
            perf.return_pct == null
              ? undefined
              : perf.return_pct >= 0
                ? "shadow-glow-positive"
                : "shadow-glow-negative"
          }
        >
          {perf.return_pct != null ? (
            <StatHero
              label={
                `${t(`periods.${period}`)} · ${t(`methods.${method}`)}` +
                (allSelected ? "" : ` · ${t("filtered")}`)
              }
              value={perf.return_pct}
              format={(n) => formatPercent(n, i18n.language, { signDisplay: "always" })}
              className={perf.return_pct >= 0 ? "text-positive" : "text-negative"}
            >
              <div className="text-xs text-text-muted">
                {formatDate(perf.start_date, i18n.language)} – {formatDate(perf.end_date, i18n.language)}
              </div>
              {benchmarkReturn != null && (
                <div className="mt-3 flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm">
                  <span className="text-text-muted">
                    {benchmarkName ?? t("benchmark")}:{" "}
                    <span className="tnum text-text">
                      {formatPercent(benchmarkReturn, i18n.language, {
                        signDisplay: "always",
                      })}
                    </span>
                  </span>
                  {excessPp != null && (
                    <span
                      className={`tnum font-medium ${
                        excessPp >= 0 ? "text-positive" : "text-negative"
                      }`}
                    >
                      {t(excessPp >= 0 ? "outperformance" : "underperformance", {
                        pp: formatNumber(Math.abs(excessPp), i18n.language, {
                          maximumFractionDigits: 1,
                        }),
                      })}
                    </span>
                  )}
                </div>
              )}
            </StatHero>
          ) : (
            <p className="text-sm text-text-muted">{t("noReturnFigure")}</p>
          )}

          <div className="mt-6">
            {method === "mwr" ? (
              <p className="text-sm text-text-muted">{t("mwrNoCurve")}</p>
            ) : curveData.length === 0 ? (
              <p className="text-sm text-text-muted">{t("noData")}</p>
            ) : (
              <LineCompareChart
                primary={curveData}
                secondary={benchmarkId ? benchmarkCurveData : undefined}
                primaryLabel={allSelected ? t("portfolio") : t("portfolioFiltered")}
                secondaryLabel={benchmarkName ?? t("benchmark")}
                formatValue={(n) => formatNumber(n, i18n.language, { maximumFractionDigits: 1 })}
              />
            )}
          </div>
        </GlassCard>
      )}
    </div>
  );
}
