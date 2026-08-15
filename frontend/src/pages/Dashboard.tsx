import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import {
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, type NetWorthPoint } from "../lib/api";
import { formatCurrency, formatDate } from "../lib/format";
import { Card } from "../components/Card";
import { DataQualityPanel } from "../components/DataQualityPanel";
import { MilestoneCard } from "../components/MilestoneCard";

type Period = "1M" | "3M" | "YTD" | "1Y" | "3Y" | "5Y" | "ALL";

const PERIODS: Period[] = ["1M", "3M", "YTD", "1Y", "3Y", "5Y", "ALL"];

// Wide ranges ask the server for coarser granularity instead of shipping
// thousands of daily points to the browser (ADR 0004 — this is the lever
// that let us skip a second, canvas-based charting library).
function rangeFor(period: Period): { from?: string; granularity: "day" | "week" | "month" } {
  const now = new Date();
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  switch (period) {
    case "1M": {
      const d = new Date(now);
      d.setMonth(d.getMonth() - 1);
      return { from: iso(d), granularity: "day" };
    }
    case "3M": {
      const d = new Date(now);
      d.setMonth(d.getMonth() - 3);
      return { from: iso(d), granularity: "day" };
    }
    case "YTD":
      return { from: `${now.getFullYear()}-01-01`, granularity: "day" };
    case "1Y": {
      const d = new Date(now);
      d.setFullYear(d.getFullYear() - 1);
      return { from: iso(d), granularity: "week" };
    }
    case "3Y": {
      const d = new Date(now);
      d.setFullYear(d.getFullYear() - 3);
      return { from: iso(d), granularity: "month" };
    }
    case "5Y": {
      const d = new Date(now);
      d.setFullYear(d.getFullYear() - 5);
      return { from: iso(d), granularity: "month" };
    }
    case "ALL":
      return { granularity: "month" };
  }
}

export function Dashboard() {
  const { t, i18n } = useTranslation("dashboard");
  const [period, setPeriod] = useState<Period>("1Y");
  const [real, setReal] = useState(false);

  const { from, granularity } = useMemo(() => rangeFor(period), [period]);

  const { data, isLoading } = useQuery({
    queryKey: ["networth", from, granularity, real],
    queryFn: () => {
      const params = new URLSearchParams({ granularity });
      if (from) params.set("from", from);
      if (real) params.set("real", "true");
      return api.get<NetWorthPoint[]>(`/api/timeseries/networth?${params}`);
    },
  });

  const latest = data && data.length > 0 ? data[data.length - 1] : null;
  const chartData =
    data?.map((p) => ({ date: p.date, value: Number(p.value_eur) })) ?? [];

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">{t("title")}</h1>

      <Card>
        <div className="text-sm text-text-muted">{t("netWorth")}</div>
        <div className="tnum mt-1 text-3xl font-semibold">
          {latest ? formatCurrency(latest.value_eur, i18n.language) : "—"}
        </div>
      </Card>

      <MilestoneCard />
      <DataQualityPanel />

      <Card>
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <h2 className="font-medium">{t("wealthCurve")}</h2>
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-1.5 text-xs text-text-muted">
              <input
                type="checkbox"
                checked={real}
                onChange={(e) => setReal(e.target.checked)}
              />
              {t("realTerms")}
            </label>
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
          </div>
        </div>

        {isLoading ? (
          <div className="flex h-64 items-center justify-center text-text-muted">
            {t("common:status.loading")}
          </div>
        ) : chartData.length === 0 ? (
          <div className="flex h-64 items-center justify-center text-center text-text-muted">
            {t("noData")}
          </div>
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
              <YAxis
                stroke="var(--text-muted)"
                fontSize={12}
                tickLine={false}
                tickFormatter={(v) => formatCurrency(v, i18n.language)}
                width={90}
              />
              <Tooltip
                formatter={(value) => formatCurrency(Number(value), i18n.language)}
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
                stroke="var(--accent)"
                strokeWidth={1.5}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </Card>
    </div>
  );
}
