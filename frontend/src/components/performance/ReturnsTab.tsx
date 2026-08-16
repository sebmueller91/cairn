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

type Period = "1M" | "3M" | "YTD" | "1Y" | "3Y" | "5Y" | "inception";
const PERIODS: Period[] = ["1M", "3M", "YTD", "1Y", "3Y", "5Y", "inception"];
type Method = "twr" | "mwr";

// Survives a reload — the benchmark is a preference, not view state.
const BENCHMARK_STORAGE_KEY = "cairn-benchmark";

export function ReturnsTab() {
  const { t, i18n } = useTranslation("performance");
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

  const { data: perf, isLoading } = useQuery({
    queryKey: ["performance", period, method, benchmarkId],
    queryFn: () => {
      const params = new URLSearchParams({ scope: "total", period, method });
      if (benchmarkId && method === "twr") params.set("benchmark_instrument_id", benchmarkId);
      return api.get<PerformanceResponse>(`/api/performance?${params}`);
    },
  });

  const periodOptions = PERIODS.map((p) => ({ value: p, label: t(`periods.${p}`) }));
  const methodOptions = (["twr", "mwr"] as Method[]).map((m) => ({
    value: m,
    label: t(`methods.${m}`),
  }));

  const curveData = perf?.curve?.map((p) => ({ date: p.date, value: p.index_value })) ?? [];
  const benchmarkCurveData = perf?.benchmark_curve?.map((p) => ({ date: p.date, value: p.index_value }));

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

      {isLoading ? (
        <GlassCard>
          <Skeleton className="h-4 w-32" />
          <Skeleton className="mt-3 h-12 w-48" />
          <Skeleton className="mt-6 h-64 w-full" />
        </GlassCard>
      ) : !perf || perf.return_pct == null ? (
        <GlassCard>
          <EmptyState icon={<TrendingUp className="size-8" aria-hidden />} title={t("noData")} />
        </GlassCard>
      ) : (
        <GlassCard className={perf.return_pct >= 0 ? "shadow-glow-positive" : "shadow-glow-negative"}>
          <StatHero
            label={`${t(`periods.${period}`)} · ${t(`methods.${method}`)}`}
            value={perf.return_pct}
            format={(n) => formatPercent(n, i18n.language, { signDisplay: "always" })}
            className={perf.return_pct >= 0 ? "text-positive" : "text-negative"}
          >
            <div className="text-xs text-text-muted">
              {formatDate(perf.start_date, i18n.language)} – {formatDate(perf.end_date, i18n.language)}
            </div>
          </StatHero>

          <div className="mt-6">
            {method === "mwr" ? (
              <p className="text-sm text-text-muted">{t("mwrNoCurve")}</p>
            ) : curveData.length === 0 ? (
              <p className="text-sm text-text-muted">{t("noData")}</p>
            ) : (
              <LineCompareChart
                primary={curveData}
                secondary={benchmarkId ? benchmarkCurveData : undefined}
                primaryLabel={t("portfolio")}
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
