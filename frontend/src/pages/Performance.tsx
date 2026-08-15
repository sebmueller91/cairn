import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  api,
  type AttributionPeriod,
  type AttributionResponse,
  type Instrument,
  type PerformanceResponse,
} from "../lib/api";
import { formatCurrency, formatDate, formatPercent } from "../lib/format";
import { Card } from "../components/Card";

type Period = "1M" | "3M" | "YTD" | "1Y" | "3Y" | "5Y" | "inception";
const PERIODS: Period[] = ["1M", "3M", "YTD", "1Y", "3Y", "5Y", "inception"];
type Method = "twr" | "mwr";

export function Performance() {
  const { t, i18n } = useTranslation(["performance", "assets", "common"]);
  const [period, setPeriod] = useState<Period>("1Y");
  const [method, setMethod] = useState<Method>("twr");
  const [benchmarkId, setBenchmarkId] = useState<string>("");
  const [granularity, setGranularity] = useState<"month" | "year">("month");

  const { data: instruments } = useQuery({
    queryKey: ["instruments"],
    queryFn: () => api.get<Instrument[]>("/api/instruments"),
  });
  const marketInstruments = (instruments ?? []).filter((i) => i.valuation_mode === "MARKET");

  const { data: perf, isLoading: perfLoading } = useQuery({
    queryKey: ["performance", period, method, benchmarkId],
    queryFn: () => {
      const params = new URLSearchParams({ scope: "total", period, method });
      if (benchmarkId && method === "twr") params.set("benchmark_instrument_id", benchmarkId);
      return api.get<PerformanceResponse>(`/api/performance?${params}`);
    },
  });

  const { data: attribution, isLoading: attrLoading } = useQuery({
    queryKey: ["attribution", granularity],
    queryFn: () =>
      api.get<AttributionResponse>(`/api/attribution?granularity=${granularity}`),
  });

  const latestPeriod: AttributionPeriod | null =
    attribution && attribution.periods.length > 0
      ? attribution.periods[attribution.periods.length - 1]
      : null;

  const chartData = useMemo(() => {
    if (!perf?.curve) return [];
    return perf.curve.map((p, idx) => ({
      date: p.date,
      value: p.index_value,
      benchmark: perf.benchmark_curve?.[idx]?.index_value,
    }));
  }, [perf]);

  const waterfallData = useMemo(() => {
    if (!latestPeriod) return [];
    const buckets: { key: string; value: number }[] = [
      { key: "deposits_withdrawals", value: Number(latestPeriod.deposits_withdrawals) },
      { key: "income", value: Number(latestPeriod.income) },
      { key: "costs", value: Number(latestPeriod.costs) },
      { key: "valuation_adjustments", value: Number(latestPeriod.valuation_adjustments) },
      { key: "fx_effect", value: Number(latestPeriod.fx_effect) },
      { key: "market_gains_losses", value: Number(latestPeriod.market_gains_losses) },
    ];
    const rows: { name: string; base: number; value: number; positive: boolean; isTotal?: boolean }[] =
      [
        {
          name: t("attribution.start"),
          base: 0,
          value: Number(latestPeriod.start_value),
          positive: true,
          isTotal: true,
        },
      ];
    let cumulative = Number(latestPeriod.start_value);
    for (const b of buckets) {
      const base = Math.min(cumulative, cumulative + b.value);
      rows.push({
        name: t(`attribution.buckets.${b.key}`),
        base,
        value: Math.abs(b.value),
        positive: b.value >= 0,
      });
      cumulative += b.value;
    }
    rows.push({
      name: t("attribution.end"),
      base: 0,
      value: Number(latestPeriod.end_value),
      positive: true,
      isTotal: true,
    });
    return rows;
  }, [latestPeriod, t]);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">{t("title")}</h1>

      <Card>
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div className="flex gap-1 rounded-md border border-border p-1">
            {PERIODS.map((p) => (
              <button
                key={p}
                onClick={() => setPeriod(p)}
                className={`rounded px-2 py-1 text-xs font-medium ${
                  p === period
                    ? "bg-accent text-accent-fg"
                    : "text-text-muted hover:text-text"
                }`}
              >
                {t(`periods.${p}`)}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-3">
            <div className="flex gap-1 rounded-md border border-border p-1">
              {(["twr", "mwr"] as Method[]).map((m) => (
                <button
                  key={m}
                  onClick={() => setMethod(m)}
                  className={`rounded px-2 py-1 text-xs font-medium ${
                    m === method
                      ? "bg-accent text-accent-fg"
                      : "text-text-muted hover:text-text"
                  }`}
                >
                  {t(`methods.${m}`)}
                </button>
              ))}
            </div>
            {method === "twr" && (
              <select
                value={benchmarkId}
                onChange={(e) => setBenchmarkId(e.target.value)}
                className="rounded-md border border-border bg-bg px-2 py-1.5 text-xs"
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
        </div>

        <div className="mb-4">
          <div className="text-sm text-text-muted">
            {t(`methods.${method}`)} · {t(`periods.${period}`)}
          </div>
          <div className="tnum mt-1 text-3xl font-semibold">
            {perf?.return_pct != null ? formatPercent(perf.return_pct, i18n.language) : "—"}
          </div>
        </div>

        {perfLoading ? (
          <div className="flex h-64 items-center justify-center text-text-muted">
            {t("common:status.loading")}
          </div>
        ) : method === "mwr" || !chartData.length ? (
          method === "mwr" ? (
            <p className="text-sm text-text-muted">{t("mwrNoCurve")}</p>
          ) : (
            <div className="flex h-64 items-center justify-center text-center text-text-muted">
              {t("noData")}
            </div>
          )
        ) : (
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={chartData}>
              <XAxis
                dataKey="date"
                tickFormatter={(d) => formatDate(d, i18n.language)}
                stroke="var(--text-muted)"
                fontSize={12}
                tickLine={false}
              />
              <YAxis stroke="var(--text-muted)" fontSize={12} tickLine={false} width={60} />
              <Tooltip
                formatter={(value) => Number(value).toFixed(1)}
                labelFormatter={(d) => formatDate(d as string, i18n.language)}
                contentStyle={{
                  background: "var(--bg-card)",
                  border: "1px solid var(--border)",
                  borderRadius: 6,
                }}
              />
              <Line
                type="monotone"
                dataKey="value"
                name={t("portfolio")}
                stroke="var(--accent)"
                strokeWidth={1.5}
                dot={false}
              />
              {benchmarkId && (
                <Line
                  type="monotone"
                  dataKey="benchmark"
                  name={t("benchmark")}
                  stroke="var(--text-muted)"
                  strokeWidth={1.5}
                  strokeDasharray="4 3"
                  dot={false}
                />
              )}
            </LineChart>
          </ResponsiveContainer>
        )}
      </Card>

      <Card>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-medium">{t("attribution.title")}</h2>
          <div className="flex gap-1 rounded-md border border-border p-1">
            {(["month", "year"] as const).map((g) => (
              <button
                key={g}
                onClick={() => setGranularity(g)}
                className={`rounded px-2 py-1 text-xs font-medium ${
                  g === granularity
                    ? "bg-accent text-accent-fg"
                    : "text-text-muted hover:text-text"
                }`}
              >
                {t(`attribution.granularity.${g}`)}
              </button>
            ))}
          </div>
        </div>

        {attrLoading ? (
          <p className="text-text-muted">{t("common:status.loading")}</p>
        ) : !latestPeriod ? (
          <p className="text-text-muted">{t("noData")}</p>
        ) : (
          <>
            <div className="mb-2 text-xs text-text-muted">
              {formatDate(latestPeriod.start_date, i18n.language)} –{" "}
              {formatDate(latestPeriod.end_date, i18n.language)}
            </div>
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={waterfallData}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                <XAxis
                  dataKey="name"
                  stroke="var(--text-muted)"
                  fontSize={11}
                  tickLine={false}
                  interval={0}
                  angle={-20}
                  textAnchor="end"
                  height={60}
                />
                <YAxis
                  stroke="var(--text-muted)"
                  fontSize={12}
                  tickLine={false}
                  tickFormatter={(v) => formatCurrency(v, i18n.language)}
                  width={90}
                />
                <Tooltip
                  formatter={(value) => formatCurrency(Number(value), i18n.language)}
                  contentStyle={{
                    background: "var(--bg-card)",
                    border: "1px solid var(--border)",
                    borderRadius: 6,
                  }}
                />
                <Bar dataKey="base" stackId="waterfall" fill="transparent" isAnimationActive={false} />
                <Bar dataKey="value" stackId="waterfall" isAnimationActive={false}>
                  {waterfallData.map((row, idx) => (
                    <Cell
                      key={idx}
                      fill={
                        row.isTotal
                          ? "var(--text-muted)"
                          : row.positive
                            ? "var(--positive)"
                            : "var(--negative)"
                      }
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </>
        )}
      </Card>
    </div>
  );
}
