import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import {
  api,
  type Instrument,
  type TaxOverviewResponse,
  type UnrealizedTaxEstimate,
} from "../../lib/api";
import { formatCurrency, formatNumber, formatPercent } from "../../lib/format";
import { GlassCard } from "../ui/GlassCard";
import { SegmentedControl } from "../ui/SegmentedControl";
import { ProgressArc } from "../ui/ProgressArc";
import { DataTable, type Column } from "../ui/DataTable";
import { Skeleton } from "../ui/Skeleton";

type YearMode = "current" | "last";

export function TaxTab() {
  const { t, i18n } = useTranslation(["tax", "common"]);
  const currentYear = new Date().getFullYear();
  const [yearMode, setYearMode] = useState<YearMode>("current");
  const [allowance, setAllowance] = useState("1000");
  const year = yearMode === "current" ? currentYear : currentYear - 1;

  const { data: instruments } = useQuery({
    queryKey: ["instruments"],
    queryFn: () => api.get<Instrument[]>("/api/instruments"),
  });
  const instrumentName = (id: number) => instruments?.find((i) => i.id === id)?.name ?? `#${id}`;

  const { data, isLoading } = useQuery({
    queryKey: ["tax", year, allowance],
    queryFn: () => api.get<TaxOverviewResponse>(`/api/tax?year=${year}&allowance=${allowance}`),
  });

  const allowanceEur = Number(data?.saver_allowance.allowance_eur ?? 0);
  const usedEur = Number(data?.saver_allowance.total_eur ?? 0);
  const remainingEur = Number(data?.saver_allowance.remaining_eur ?? 0);
  const usedPct = allowanceEur > 0 ? Math.min(100, (usedEur / allowanceEur) * 100) : 0;
  const arcColor = remainingEur < 0 ? "var(--negative)" : "var(--accent)";

  const columns: Column<UnrealizedTaxEstimate>[] = [
    {
      key: "instrument",
      header: t("common:fields.name"),
      render: (row) => instrumentName(row.instrument_id),
    },
    {
      key: "quantity",
      header: t("common:fields.quantity"),
      align: "right",
      render: (row) => formatNumber(row.quantity, i18n.language, { maximumFractionDigits: 8 }),
    },
    {
      key: "costBasis",
      header: t("unrealized.costBasis"),
      align: "right",
      render: (row) => (
        <span className="sensitive">{formatCurrency(row.cost_basis_eur, i18n.language)}</span>
      ),
    },
    {
      key: "currentValue",
      header: t("unrealized.currentValue"),
      align: "right",
      render: (row) => (
        <span className="sensitive">{formatCurrency(row.current_value_eur, i18n.language)}</span>
      ),
    },
    {
      key: "unrealizedPl",
      header: t("unrealized.unrealizedPl"),
      align: "right",
      render: (row) => (
        <span
          className={`sensitive ${
            Number(row.unrealized_pl_eur) >= 0 ? "text-positive" : "text-negative"
          }`}
        >
          {formatCurrency(row.unrealized_pl_eur, i18n.language)}
        </span>
      ),
    },
    {
      key: "estimatedTax",
      header: t("unrealized.estimatedTax"),
      align: "right",
      render: (row) => (
        <span className="sensitive">{formatCurrency(row.estimated_tax_eur, i18n.language)}</span>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      {data?.vorabpauschale_reminder && (
        <div className="rounded-card border border-warning bg-warning/10 p-4 backdrop-blur-glass md:p-5">
          <div className="flex items-start gap-3">
            <AlertTriangle className="mt-0.5 size-5 shrink-0 text-warning" aria-hidden />
            <p className="text-sm">{data.vorabpauschale_reminder}</p>
          </div>
        </div>
      )}

      <GlassCard>
        <div className="mb-5 flex flex-wrap items-end gap-4">
          <div>
            <label className="mb-1 block text-xs text-text-muted">{t("year")}</label>
            <SegmentedControl
              options={[
                { value: "current" as const, label: t("thisYear") },
                { value: "last" as const, label: t("lastYear") },
              ]}
              value={yearMode}
              onChange={setYearMode}
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-text-muted">{t("allowance")}</label>
            <input
              value={allowance}
              onChange={(e) => setAllowance(e.target.value)}
              inputMode="decimal"
              className="h-8 w-28 rounded-full border border-border bg-bg-subtle px-3 text-xs text-text focus:outline-none focus:ring-1 focus:ring-accent"
            />
          </div>
        </div>

        {isLoading || !data ? (
          <div className="flex flex-col items-center gap-4 sm:flex-row">
            <Skeleton className="size-32 shrink-0 rounded-full" />
            <div className="grid flex-1 grid-cols-2 gap-4 sm:grid-cols-3">
              {Array.from({ length: 5 }, (_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-6 sm:flex-row sm:items-center">
            <ProgressArc
              pct={usedPct}
              color={arcColor}
              label={formatPercent(usedPct / 100, i18n.language, { maximumFractionDigits: 0 })}
              sublabel={t("ofAllowance")}
            />
            <div className="grid flex-1 grid-cols-2 gap-4 sm:grid-cols-3">
              <div>
                <div className="text-xs text-text-muted">{t("allowance")}</div>
                <div className="tnum sensitive mt-0.5 text-lg font-medium">
                  {formatCurrency(data.saver_allowance.allowance_eur, i18n.language)}
                </div>
              </div>
              <div>
                <div className="text-xs text-text-muted">{t("realizedGains")}</div>
                <div className="tnum sensitive mt-0.5 text-lg font-medium">
                  {formatCurrency(data.saver_allowance.realized_gains_eur, i18n.language)}
                </div>
              </div>
              <div>
                <div className="text-xs text-text-muted">{t("investmentIncome")}</div>
                <div className="tnum sensitive mt-0.5 text-lg font-medium">
                  {formatCurrency(data.saver_allowance.investment_income_eur, i18n.language)}
                </div>
              </div>
              <div>
                <div className="text-xs text-text-muted">{t("used")}</div>
                <div className="tnum sensitive mt-0.5 text-lg font-medium">
                  {formatCurrency(data.saver_allowance.total_eur, i18n.language)}
                </div>
              </div>
              <div>
                <div className="text-xs text-text-muted">{t("remaining")}</div>
                <div
                  className={`tnum sensitive mt-0.5 text-lg font-medium ${
                    remainingEur < 0 ? "text-negative" : "text-positive"
                  }`}
                >
                  {formatCurrency(data.saver_allowance.remaining_eur, i18n.language)}
                </div>
              </div>
            </div>
          </div>
        )}
      </GlassCard>

      <GlassCard className="p-0">
        <div className="p-4 pb-0 md:p-5 md:pb-0">
          <h2 className="font-medium">{t("unrealized.title")}</h2>
        </div>
        {isLoading ? (
          <div className="p-4 md:p-5">
            <Skeleton className="h-40 w-full" />
          </div>
        ) : !data?.unrealized.length ? (
          <p className="p-4 text-text-muted md:p-5">{t("common:status.empty")}</p>
        ) : (
          <DataTable
            columns={columns}
            rows={data.unrealized}
            rowKey={(row) => `${row.account_id}-${row.instrument_id}`}
            className="mt-3"
          />
        )}
      </GlassCard>

      <p className="text-xs text-text-muted">{t("disclaimer")}</p>
    </div>
  );
}
